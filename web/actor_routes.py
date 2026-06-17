import io
import time
import json
import html
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp, get_size
from info import BIN_CHANNEL
from database.ia_filterdb import actors, get_actor_search_results
from web.web_assets import build_page, get_auth, form_wrapper

actor_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 🛠️ HELPER: Get TG Photo ID safely
# ─────────────────────────────────────────────────────────
def get_tg_photo_id(msg):
    return msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id

# ─────────────────────────────────────────────────────────
# 🎭 PUBLIC VIEW: ACTORS DIRECTORY CATALOG PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actors')
async def actors_directory_page(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
        
    all_actors = await actors.find({}).sort("created_at", -1).to_list(length=200)
    
    admin_btn = f'''<div style="display:flex; justify-content:flex-end; margin-bottom:25px;"><a href="/admin/create_actor" style="background:var(--accent); color:#fff; padding:12px 24px; border-radius:8px; font-weight:700; text-decoration:none; font-size:14px; box-shadow:0 4px 15px rgba(229,9,20,0.3);">➕ Create New Actor</a></div>''' if role == 'admin' else ""
        
    if not all_actors:
        actors_grid = '<div style="color:var(--muted); text-align:center; padding:60px 20px; grid-column:1/-1;">🎭 No actor profiles created yet.</div>'
    else:
        actors_grid = '<div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:20px;">'
        for act in all_actors:
            act_id, name = str(act["_id"]), html.escape(act.get('name', ''))
            photo_v = int(act.get("photo_updated_at") or act.get("created_at") or 0)
            actors_grid += f'''
            <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; overflow:hidden; transition:0.2s; cursor:pointer;" onclick="window.location.href='/actor/{act_id}'">
                <div style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                    <img src="/api/actor/photo?id={act_id}&v={photo_v}" style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover;" loading="lazy">
                </div>
                <div style="padding:12px; text-align:center;"><div style="font-size:14px; font-weight:700; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{name}</div></div>
            </div>'''
        actors_grid += '</div>'

    page_body = f'''<div class="main" style="padding-top:30px; max-width:1100px; margin:0 auto; padding:0 20px;">
        <div style="margin-bottom:20px;"><h1 style="font-size:28px; font-weight:900; color:var(--text); margin-bottom:4px;">🎭 Actors Catalog</h1><p style="color:var(--muted); font-size:14px;">Browse verified star profiles and linked content grids.</p></div>
        {admin_btn}{actors_grid}
    </div>'''
    return build_page("Actors Directory - Fast Finder", page_body, "", "actors", role)

# ─────────────────────────────────────────────────────────
# 🎭 ADMIN VIEW: CREATE ACTOR PROFILE PAGE FORM
# ─────────────────────────────────────────────────────────
@actor_routes.get('/admin/create_actor')
async def create_actor_page(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')
        
    content = '''<form action="/api/create_actor" method="post" enctype="multipart/form-data">
        <input type="text" name="name" placeholder="Actor Full Name" required>
        <textarea name="bio" placeholder="Actor Biography..." style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; min-height:100px; margin-bottom:15px;" required></textarea>
        <div class="scard-label" style="margin-bottom:4px; color:var(--muted);">Search Tags (Comma Separated)</div>
        <input type="text" name="tags" placeholder="e.g. SRK, Shahrukh" style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; margin-bottom:15px;">
        <div class="scard-label" style="margin-bottom:8px; color:var(--muted);">Profile Photo</div>
        <input type="file" name="photo" accept="image/*" required style="padding:10px 0; color:var(--text);">
        <button class="submit-btn" type="submit" style="background:var(--accent); color:#fff; width:100%; padding:14px; border:0; border-radius:6px; font-weight:700; cursor:pointer; margin-top:10px;">Create Profile</button>
    </form><div style="margin-top:15px; text-align:center;"><a href="/actors" style="color:var(--muted); text-decoration:none; font-size:13px;">← Back to Catalog</a></div>'''
    return build_page("Create Actor", form_wrapper("Add New Actor", content, req.query.get('err',''), req.query.get('msg','')), "login-bg", "actors", role)

# ─────────────────────────────────────────────────────────
# ⚙️ ADMIN API: UPLOAD TO TG & SAVE TO MONGO
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/create_actor')
async def api_create_actor(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
        
    try:
        reader = await req.multipart()
        d = {}
        while True:
            part = await reader.next()
            if not part: break
            d[part.name] = await part.read()

        name = d.get('name', b'').decode().strip()
        bio = d.get('bio', b'').decode().strip()
        tags_raw = d.get('tags', b'').decode().strip()
        image_bytes = d.get('photo')

        if not name or not bio or not image_bytes: return web.HTTPFound('/admin/create_actor?err=All fields are required!')

        with io.BytesIO(image_bytes) as img_buffer:
            img_buffer.name = f"{name.replace(' ', '_')}.jpg"
            msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)

        if not msg or not msg.photo: return web.HTTPFound('/admin/create_actor?err=Telegram Upload Failed!')
        
        now_ts = int(time.time())
        await actors.insert_one({
            "name": name, "bio": bio, "tags": [t.strip() for t in tags_raw.split(",") if t.strip()],
            "photo_url": f"TG_ID:{get_tg_photo_id(msg)}", "photo_updated_at": now_ts,
            "social_links": {"instagram": "", "youtube": "", "twitter": ""},
            "gallery": [], "created_at": now_ts
        })
        return web.HTTPFound('/actors?msg=Actor Profile created successfully!')
    except Exception as e:
        return web.HTTPFound(f'/admin/create_actor?err=Server Error: {str(e)}')

# ─────────────────────────────────────────────────────────
# 🖼️ PHOTO ENGINE (Optimized)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/photo')
async def get_actor_photo(req):
    actor_id, img_index = req.query.get("id"), req.query.get("gallery_idx")
    if not actor_id: return web.Response(status=400)
    
    try:
        doc = await actors.find_one({"_id": ObjectId(actor_id)})
        if not doc: return web.Response(status=404)
        
        raw_url = doc.get("gallery", [])[int(img_index)] if img_index is not None else doc.get("photo_url")
        if not raw_url or not raw_url.startswith("TG_ID:"): return web.Response(status=404)
        
        headers = {"Cache-Control": "public, max-age=31536000, immutable", "Content-Disposition": f'inline; filename="{"photo" if img_index else "avatar"}.jpg"'}
        file_data = await temp.BOT.download_media(raw_url.replace("TG_ID:", ""), in_memory=True)
        if not file_data: return web.Response(status=404)
        
        body_bytes = file_data.getvalue()
        file_data.close()
        return web.Response(body=body_bytes, content_type="image/jpeg", headers=headers)
    except Exception: return web.Response(status=500)

# ─────────────────────────────────────────────────────────
# 🌐 PUBLIC VIEW: ACTOR PROFILE MASTER INTERFACE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actor/{id}')
async def actor_profile_display(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    
    try:
        actor_id = req.match_info['id']
        actor = await actors.find_one({"_id": ObjectId(actor_id)})
        if not actor: return web.Response(text="Actor Not Found", status=404)
    except: return web.Response(text="Invalid ID", status=400)
        
    actor_name, tags_list = actor["name"], actor.get("tags", [])
    social, gallery_list = actor.get("social_links", {}), actor.get("gallery", [])
    
    tags_chips = ''.join([f'<span style="background:var(--bg3); border:1px solid var(--border); color:var(--muted); font-size:11px; padding:3px 8px; border-radius:4px; font-weight:600; margin:2px;">#{html.escape(t)}</span>' for t in tags_list])
    
    social_html = ""
    for k, v, c, n in [('instagram','#ff007f','📸 Instagram', social.get('instagram')), ('youtube','#ff0000','📺 YouTube', social.get('youtube')), ('twitter','#1da1f2','🐦 Twitter', social.get('twitter'))]:
        if n: social_html += f'<a href="{html.escape(n)}" target="_blank" style="background:{v}; color:#fff; padding:6px 14px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:700;">{c}</a> '

    gallery_grid_html = f'''<div style="background:var(--card); border:1px dashed var(--border); padding:20px; border-radius:8px; text-align:center; margin-bottom:20px;"><form action="/api/actor/gallery_upload" method="post" enctype="multipart/form-data" style="margin:0;"><input type="hidden" name="actor_id" value="{actor_id}"><label style="background:var(--accent); color:#fff; padding:10px 20px; border-radius:6px; font-weight:700; cursor:pointer; font-size:13px; display:inline-block;">📂 Add Image<input type="file" name="gallery_img" accept="image/*" style="display:none;" onchange="this.form.submit()"></label></form></div>''' if role == 'admin' else ""
    
    if not gallery_list: gallery_grid_html += '<div style="color:var(--muted); text-align:center; padding:40px;">🖼️ Gallery is empty.</div>'
    else:
        gallery_grid_html += '<div class="gallery-grid">'
        for i in range(len(gallery_list)):
            del_btn = f'<button class="gallery-del-btn" onclick="deleteGalleryImage(\'{actor_id}\', {i}, event)">🗑️ Delete</button>' if role == 'admin' else ""
            gallery_grid_html += f'<div class="gallery-item-wrap" onclick="openLightbox(\'/api/actor/photo?id={actor_id}&gallery_idx={i}\')"><img src="/api/actor/photo?id={actor_id}&gallery_idx={i}" class="gallery-item" loading="lazy">{del_btn}</div>'
        gallery_grid_html += '</div>'

    admin_actions = f'''<div style="display:flex; gap:10px; margin-top:10px; flex-wrap:wrap;"><button onclick="openActorEditModal()" style="background:var(--bg4); border:1px solid var(--border); color:var(--text); padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">✏️ Edit Profile</button><button onclick="deleteActorProfile('{actor_id}')" style="background:rgba(160,8,8,.78); border:1px solid rgba(229,9,20,.45); color:#fff; padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">🗑️ Delete Profile</button><label style="background:var(--bg3); border:1px dashed var(--border); color:var(--text); padding:7px 14px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; display:inline-block;">📸 Change Avatar<input type="file" id="avatarUpdateInput" accept="image/*" style="display:none;" onchange="updateActorAvatar('{actor_id}')"></label></div>''' if role == 'admin' else ""
        
    safe_bio = html.escape(actor.get("bio", ""))
    photo_v = int(actor.get("photo_updated_at") or actor.get("created_at") or 0)

    tab_engine_ui = f'''
    <style>
        .actor-tab-bar {{ display:flex; gap:10px; border-bottom:2px solid var(--border); margin-bottom:25px; }}
        .actor-tab {{ background:none; border:none; color:var(--muted); padding:12px 20px; font-size:15px; font-weight:700; cursor:pointer; position:relative; font-family:inherit; }}
        .actor-tab.active {{ color:var(--text); }} .actor-tab.active::after {{ content:''; position:absolute; bottom:-2px; left:0; right:0; height:2px; background:var(--accent); }}
        .actor-panel {{ display:none; }} .actor-panel.active {{ display:block; }}
        .gallery-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(140px, 1fr)); gap:14px; }}
        .gallery-item-wrap {{ position:relative; border-radius:8px; overflow:hidden; border:1px solid var(--border); aspect-ratio:1; cursor:pointer; }}
        .gallery-item {{ width:100%; height:100%; object-fit:cover; transition:transform 0.2s; }} .gallery-item-wrap:hover .gallery-item {{ transform:scale(1.04); }}
        .gallery-del-btn {{ position:absolute; bottom:8px; left:50%; transform:translateX(-50%); background:rgba(160,8,8,.85); border:1px solid var(--accent); color:#fff; padding:4px 10px; border-radius:4px; font-size:10px; font-weight:700; cursor:pointer; opacity:0; transition:opacity 0.15s; z-index:5; }}
        .gallery-item-wrap:hover .gallery-del-btn {{ opacity:1; }}
        .lightbox {{ position:fixed; inset:0; background:rgba(0,0,0,.92); backdrop-filter:blur(15px); z-index:99999; display:none; align-items:center; justify-content:center; opacity:0; transition:opacity 0.2s; }}
        .lightbox.open {{ display:flex; opacity:1; }} .lightbox-img {{ max-width:92%; max-height:88vh; object-fit:contain; border-radius:6px; transform:scale(.95); transition:transform .2s; }}
        .lightbox.open .lightbox-img {{ transform:scale(1); }} .lightbox-close {{ position:absolute; top:20px; right:25px; background:none; border:none; color:#fff; font-size:32px; cursor:pointer; }}
        .actor-header-wrap {{ display:flex; gap:25px; background:var(--card); border:1px solid var(--border); padding:25px; border-radius:12px; margin-bottom:35px; flex-direction:column; align-items:center; }}
        .avatar-box-master {{ width:100%; max-width:340px; aspect-ratio:3/4; background:var(--bg3); border-radius:8px; overflow:hidden; border:1px solid var(--border); }}
        @media(min-width:768px){{ .actor-header-wrap {{ flex-direction:row; align-items:stretch; }} .avatar-box-master {{ width:260px; max-width:none; }} }}
        /* Form, Grid & CDD styles minified */
        .search-zone-actor {{ display:flex; flex-wrap:wrap; gap:10px; padding-bottom:16px; align-items:center; }}
        .search-wrap-actor {{ flex:1; min-width:200px; display:flex; background:var(--bg3); border:1.5px solid var(--border); border-radius:12px; padding:0 18px; min-height:38px; }}
        .search-input-actor {{ flex:1; background:transparent; border:none; outline:none; color:var(--text); font-weight:600; font-family:inherit; }}
        .search-btn-actor {{ background:var(--accent); color:#fff; border:none; border-radius:12px; padding:0 20px; font-weight:700; cursor:pointer; }}
        .res-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:16px; margin-bottom:24px; }}
        .file-card {{ background:var(--card); border-radius:6px; overflow:hidden; border:1px solid var(--border); cursor:pointer; transition:transform 0.2s; }} .file-card:hover {{ transform:translateY(-4px); }}
        .poster-box {{ position:relative; padding-top:56.25%; background:var(--bg3); }} .fc-poster {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }}
        .fc-body {{ padding:10px; }} .fc-name {{ font-size:12.5px; font-weight:600; line-height:1.45; color:var(--text); }}
        .pagination {{ display:flex; justify-content:center; gap:12px; margin-top:20px; }} .pg-btn {{ background:var(--bg4); color:var(--text); border:1px solid var(--border); padding:8px 18px; border-radius:6px; cursor:pointer; }}
    </style>

    <div class="main" style="padding-top:30px; max-width:1100px; margin:0 auto; padding:0 20px;">
        <div style="margin-bottom:15px;"><a href="/actors" style="color:var(--muted); text-decoration:none; font-size:14px; font-weight:700;">← Back to Catalog</a></div>
        <div class="actor-header-wrap">
            <div class="avatar-box-master"><img id="actorMasterAvatarImage" src="/api/actor/photo?id={actor_id}&v={photo_v}" style="width:100%; height:100%; object-fit:cover;"></div>
            <div style="flex:1; display:flex; flex-direction:column; justify-content:center;">
                <h1 style="font-size:32px; font-weight:900; margin-bottom:2px;">{html.escape(actor_name)}</h1>
                <div style="display:flex; flex-wrap:wrap; gap:6px;">{tags_chips}</div>
                <div style="display:flex; gap:12px; margin-top:12px; flex-wrap:wrap;">{social_html}</div>
                {admin_actions}
            </div>
        </div>

        <div class="actor-tab-bar">
            <button class="actor-tab active" onclick="switchTab('info', this)">ℹ️ Info</button>
            <button class="actor-tab" onclick="switchTab('video', this)">🎬 Video</button>
            <button class="actor-tab" onclick="switchTab('gallery', this)">🖼️ Gallery</button>
        </div>

        <div id="tab-info" class="actor-panel active"><div style="background:var(--card); border:1px solid var(--border); padding:25px; border-radius:8px; line-height:1.7; white-space:pre-line;">{safe_bio}</div></div>
        
        <div id="tab-video" class="actor-panel">
            <div class="search-zone-actor">
                <div class="search-wrap-actor"><input type="text" id="actor_movie_q" placeholder="Search inside actor movies..." class="search-input-actor"></div>
                <button onclick="actOffset=0; triggerSearch()" class="search-btn-actor">Search</button>
                <select id="cddCol" onchange="actOffset=0; triggerSearch()" style="background:var(--bg3); color:var(--text); border:1.5px solid var(--border); padding:8px; border-radius:8px; outline:none;">
                    <option value="all">📂 All Collections</option><option value="primary">🟢 Primary</option><option value="cloud">🔵 Cloud</option><option value="archive">🟠 Archive</option>
                </select>
                <select id="cddMode" onchange="actOffset=0; triggerSearch()" style="background:var(--bg3); color:var(--text); border:1.5px solid var(--border); padding:8px; border-radius:8px; outline:none;">
                    <option value="tg">🖼️ Original TG Thumb</option><option value="none">⚡ Text Only</option>
                </select>
            </div>
            <div id="actor_video_results" class="res-grid"></div>
            <div class="pagination" id="actor_page_box" style="display:none;">
                <button class="pg-btn" id="actor_pBtn" onclick="if(actCurPage>1){{actCurPage--; actOffset-=actLimit; triggerSearch();}}">Previous</button>
                <span class="pg-info" id="actor_pgInfo" style="align-self:center; color:var(--muted); font-weight:bold;">Page 1</span>
                <button class="pg-btn" id="actor_nBtn" onclick="if(actNextOffset){{actCurPage++; actOffset=actNextOffset; triggerSearch();}}">Next</button>
            </div>
        </div>

        <div id="tab-gallery" class="actor-panel">{gallery_grid_html}</div>
    </div>

    <div id="actorLightboxModal" class="lightbox" onclick="closeLightbox()"><button class="lightbox-close">&times;</button><img id="lightboxTargetImg" class="lightbox-img" src="" onclick="event.stopPropagation()"></div>

    <div class="edit-modal" id="actorEditModal" onclick="if(event.target===this)closeActorEditModal()" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.8); z-index:999; align-items:center; justify-content:center;">
        <div style="background:var(--card); padding:25px; border-radius:12px; width:90%; max-width:550px; position:relative;">
            <button onclick="closeActorEditModal()" style="position:absolute; top:15px; right:20px; background:none; border:none; color:var(--muted); font-size:24px; cursor:pointer;">&#10005;</button>
            <h3 style="margin-top:0;">✏️ Edit Profile</h3>
            <form action="/api/actor/update_profile" method="post">
                <input type="hidden" name="actor_id" value="{actor_id}">
                <input type="text" name="name" value="{html.escape(actor_name)}" style="width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:15px; border-radius:6px;" required>
                <textarea name="bio" style="width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:15px; border-radius:6px; min-height:100px;" required>{safe_bio}</textarea>
                <input type="text" name="tags" value="{html.escape(', '.join(tags_list))}" placeholder="Tags" style="width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:15px; border-radius:6px;">
                <input type="url" name="insta" value="{html.escape(social.get('instagram',''))}" placeholder="Instagram URL" style="width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:10px; border-radius:6px;">
                <input type="url" name="yt" value="{html.escape(social.get('youtube',''))}" placeholder="YouTube URL" style="width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:10px; border-radius:6px;">
                <input type="url" name="twitter" value="{html.escape(social.get('twitter',''))}" placeholder="Twitter URL" style="width:100%; background:var(--bg); border:1px solid var(--border); padding:12px; color:var(--text); margin-bottom:15px; border-radius:6px;">
                <button type="submit" style="width:100%; background:var(--accent); color:#fff; border:none; padding:12px; border-radius:6px; font-weight:bold; cursor:pointer;">Save Changes</button>
            </form>
        </div>
    </div>

    <script>
        let actCurPage=1, actOffset=0, actNextOffset="", actLimit=21;

        function switchTab(id, btn) {{
            document.querySelectorAll('.actor-panel, .actor-tab').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-'+id).classList.add('active'); btn.classList.add('active');
            if(id==='video' && !document.getElementById('actor_video_results').innerHTML) triggerSearch();
        }}
        function openLightbox(src) {{ document.getElementById('lightboxTargetImg').src=src; const lb=document.getElementById('actorLightboxModal'); lb.style.display='flex'; setTimeout(()=>lb.classList.add('open'),10); }}
        function closeLightbox() {{ const lb=document.getElementById('actorLightboxModal'); lb.classList.remove('open'); setTimeout(()=>lb.style.display='none',200); }}
        function openActorEditModal() {{ document.getElementById('actorEditModal').style.display='flex'; }}
        function closeActorEditModal() {{ document.getElementById('actorEditModal').style.display='none'; }}

        async function triggerSearch() {{
            const q = document.getElementById('actor_movie_q').value.trim();
            const col = document.getElementById('cddCol').value, mode = document.getElementById('cddMode').value;
            const grid = document.getElementById('actor_video_results');
            grid.innerHTML = '<div style="text-align:center; width:100%; grid-column:1/-1; padding:40px;">Loading...</div>';
            
            try {{
                const r = await fetch(`/api/actor/search?q=${{encodeURIComponent(q)}}&offset=${{actOffset}}&col=${{col}}&mode=${{mode}}&id={actor_id}`);
                const d = await r.json();
                if(!d.results?.length) {{ grid.innerHTML = '<div style="grid-column:1/-1; text-align:center;">No results found.</div>'; document.getElementById('actor_page_box').style.display='none'; return; }}
                
                grid.innerHTML = d.results.map(f => `
                    <div class="file-card" onclick="window.open('${{f.watch}}','_blank')">
                        ${{mode==='none' ? '' : `<div class="poster-box"><img src="${{f.tg_thumb}}" class="fc-poster"></div>`}}
                        <div class="fc-body"><div class="fc-name">${{f.name}}</div>
                        <div style="font-size:11px; color:var(--muted); margin-top:5px;">${{f.size}} • ${{f.type}} • ${{f.source}}</div></div>
                    </div>`).join('');
                
                actNextOffset = d.next_offset;
                document.getElementById('actor_page_box').style.display = 'flex';
                document.getElementById('actor_pBtn').disabled = actOffset === 0;
                document.getElementById('actor_nBtn').disabled = !actNextOffset;
                document.getElementById('actor_pgInfo').textContent = `Page ${{actCurPage}}`;
            }} catch(e) {{ grid.innerHTML = '<div style="grid-column:1/-1; text-align:center;">Error fetching data.</div>'; }}
        }}

        async function updateActorAvatar(actorId) {{
            const file = document.getElementById('avatarUpdateInput').files[0];
            if(!file) return;
            const fd = new FormData(); fd.append('actor_id', actorId); fd.append('photo', file);
            try {{
                const r = await fetch('/api/actor/update_avatar', {{ method:'POST', body:fd }});
                const d = await r.json();
                if(d.success) {{ document.getElementById('actorMasterAvatarImage').src = `/api/actor/photo?id=${{actorId}}&v=${{d.photo_updated_at}}`; alert('Updated!'); }}
                else alert(d.error);
            }} catch(e) {{ alert('Network Error'); }}
        }}

        async function deleteGalleryImage(id, idx, e) {{
            e.stopPropagation(); if(!confirm("Delete this photo?")) return;
            try {{
                const r = await fetch('/api/actor/gallery_delete', {{ method:'POST', body:JSON.stringify({{actor_id:id, index:idx}}), headers:{{'Content-Type':'application/json'}} }});
                if((await r.json()).success) window.location.reload(); else alert("Failed");
            }} catch(e) {{ alert("Error"); }}
        }}

        async function deleteActorProfile(id) {{
            if(!confirm("Delete actor profile?")) return;
            try {{
                if((await (await fetch('/api/actor/delete?id='+id, {{method:'POST'}})).json()).success) window.location.href='/actors';
            }} catch(e) {{ alert("Error"); }}
        }}

        document.getElementById('actor_movie_q').addEventListener('keydown', e => {{ if(e.key==='Enter') {{actCurPage=1; actOffset=0; triggerSearch();}} }});
    </script>
    '''
    return build_page(f"{actor_name} - Profile", tab_engine_ui, "", "actors", role)

# ─────────────────────────────────────────────────────────
# ⚙️ ADMIN API: SEARCH PIPELINE FOR ACTOR PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/search')
async def api_actor_search_handler(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"error": "Unauthorized"}, status=403)
    
    actor_id, q_custom = req.query.get("id"), req.query.get("q", "").strip()
    off, col = int(req.query.get("offset", "0")), req.query.get("col", "all").lower()
    
    if not actor_id: return web.json_response({"results": []})
    
    actor = await actors.find_one({"_id": ObjectId(actor_id)})
    if not actor: return web.json_response({"results": []})
    
    tags_list = actor.get("tags", [])
    search_query, final_tags = (q_custom, []) if q_custom else (tags_list[0] if tags_list else "", tags_list)
    if not search_query: return web.json_response({"results": [], "next_offset": ""})
        
    all_m, next_offset = await get_actor_search_results(search_query, final_tags, max_results=21, offset=off, collection_type=col)
    
    results = [{
        "file_id": d.get("_id"), "name": d.get("file_name", "Unknown File"), "size": get_size(d.get("file_size", 0)),
        "type": d.get("file_type", "document").upper(), "source": d.get("source_col", "primary").capitalize(),
        "tg_thumb": f"/api/thumb?file_id={d.get('_id')}&col={d.get('source_col', 'primary')}&v={(d.get('thumb_url', '')[-8:] if str(d.get('thumb_url', '')).startswith('TG_ID:') else '0')}",
        "watch": f"/setup_stream?file_id={d.get('file_ref') or d.get('_id')}&mode=watch"
    } for d in all_m]
        
    return web.json_response({"results": results, "next_offset": next_offset})

# ─────────────────────────────────────────────────────────
# ⚙️ ADMIN API: UPDATE PROFILE DETAILS
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_profile')
async def api_actor_update_profile(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    d = await req.post()
    actor_id, name, bio = d.get('actor_id'), d.get('name', '').strip(), d.get('bio', '').strip()
    if not actor_id or not name or not bio: return web.HTTPFound('/actors?err=Missing assets data')
    
    await actors.update_one({"_id": ObjectId(actor_id)}, {"$set": {
        "name": name, "bio": bio, "tags": [t.strip() for t in d.get('tags', '').split(",") if t.strip()],
        "social_links": {"instagram": d.get('insta','').strip(), "youtube": d.get('yt','').strip(), "twitter": d.get('twitter','').strip()}
    }})
    return web.HTTPFound(f'/actor/{actor_id}?msg=Profile synced successfully!')

# ─────────────────────────────────────────────────────────
# 🖼️ ADMIN API: UPDATE AVATAR
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_avatar')
async def api_actor_update_avatar(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    try:
        data = await req.post()
        actor_id, photo_part = data.get("actor_id"), data.get("photo")
        if not actor_id or not photo_part: return web.json_response({"success": False, "error": "Invalid assets data"})
            
        with io.BytesIO(photo_part.file.read()) as img_buffer:
            img_buffer.name = f"avatar_{actor_id}_{int(time.time())}.jpg"
            msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)
            
        if not msg or not msg.photo: return web.json_response({"success": False, "error": "Upload failed"})
        
        now = int(time.time())
        await actors.update_one({"_id": ObjectId(actor_id)}, {"$set": {"photo_url": f"TG_ID:{get_tg_photo_id(msg)}", "photo_updated_at": now}})
        return web.json_response({"success": True, "photo_updated_at": now})
    except Exception as e: return web.json_response({"success": False, "error": str(e)})

# ─────────────────────────────────────────────────────────
# 🖼️ ADMIN API: GALLERY UPLOAD / DELETE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/gallery_upload')
async def api_actor_gallery_upload(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    try:
        reader = await req.multipart()
        d = {}
        while True:
            part = await reader.next()
            if not part: break
            d[part.name] = await part.read()
            
        actor_id, image_bytes = d.get('actor_id', b'').decode().strip(), d.get('gallery_img')
        if not actor_id or not image_bytes: return web.HTTPFound('/actors?err=Upload failure')
        
        with io.BytesIO(image_bytes) as img_buffer:
            img_buffer.name = f"gallery_{actor_id}_{int(time.time())}.jpg"
            msg = await temp.BOT.send_photo(chat_id=BIN_CHANNEL, photo=img_buffer)
            
        if not msg or not msg.photo: return web.HTTPFound(f'/actor/{actor_id}?err=Upload Failed')
        
        await actors.update_one({"_id": ObjectId(actor_id)}, {"$push": {"gallery": f"TG_ID:{get_tg_photo_id(msg)}"}})
        return web.HTTPFound(f'/actor/{actor_id}?msg=Uploaded successfully!')
    except Exception as e: return web.HTTPFound(f'/actors?err=Crash: {str(e)}')

@actor_routes.post('/api/actor/gallery_delete')
async def api_actor_gallery_delete(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    try:
        body = await req.json()
        actor_id, idx = body.get("actor_id"), body.get("index")
        actor = await actors.find_one({"_id": ObjectId(actor_id)})
        
        if not actor or "gallery" not in actor: return web.json_response({"success": False})
        gallery = actor["gallery"]
        if 0 <= idx < len(gallery):
            del gallery[idx]
            await actors.update_one({"_id": ObjectId(actor_id)}, {"$set": {"gallery": gallery}})
            return web.json_response({"success": True})
        return web.json_response({"success": False})
    except Exception: return web.json_response({"success": False})

# ─────────────────────────────────────────────────────────
# 🗑️ ADMIN API: DELETE ACTOR PROFILE COMPLETELY
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/delete')
async def api_actor_delete(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403)
    
    actor_id = req.query.get("id")
    if not actor_id: return web.json_response({"error": "Missing ID"}, status=400)
    
    try:
        await actors.delete_one({"_id": ObjectId(actor_id)})
        return web.json_response({"success": True})
    except Exception as e: return web.json_response({"error": str(e)}, status=500)
