import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
import json
import logging
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth
import firestore_models  # Import our new Firestore models
from collections import defaultdict
import mimetypes

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Ensure logs go to console/terminal
    ]
)
logger = logging.getLogger(__name__)

# Change Werkzeug logger level to INFO for development
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)  # Changed from ERROR to INFO

# Also add more verbose logging for Firebase auth
firebase_logger = logging.getLogger('firebase_admin')
firebase_logger.setLevel(logging.DEBUG)  # Set Firebase logging to DEBUG level

# Initialize Flask app and Socket.IO
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ship_game_secret_key')

# Initialize Firebase and Firestore (instead of SQLAlchemy)
firebase_cred_path = os.environ.get('FIREBASE_CREDENTIALS', 'firebasekey.json')
cred = credentials.Certificate(firebase_cred_path)
firebase_app = firebase_admin.initialize_app(cred)
db = firestore.client()

# Initialize our Firestore models with the Firestore client
firestore_models.init_firestore(db)

# Set up Socket.IO
socketio = SocketIO(app, cors_allowed_origins=os.environ.get('SOCKETIO_CORS_ALLOWED_ORIGINS', '*'))

# Keep a session cache for quick access
players = {}
islands = {}

# Add this near your other global variables
last_db_update = defaultdict(float)  # Track last database update time for each player
DB_UPDATE_INTERVAL = 5.0  # seconds between database updates

# Add these MIME type registrations after your existing imports
# Register GLB and GLTF MIME types
mimetypes.add_type('model/gltf-binary', '.glb')
mimetypes.add_type('model/gltf+json', '.gltf')

# Set up the static file directory path
STATIC_FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
os.makedirs(STATIC_FILES_DIR, exist_ok=True)

# Load data from Firestore on startup
def load_data_from_firestore():
    # Load players
    db_players = firestore_models.Player.get_all()
    for player in db_players:
        # Set all players to inactive on server start
        if player.get('active', False):
            firestore_models.Player.update(player['id'], active=False)
            player['active'] = False
        players[player['id']] = player
    
    # Load islands
    db_islands = firestore_models.Island.get_all()
    for island in db_islands:
        islands[island['id']] = island
    
    logger.info(f"Loaded {len(players)} players and {len(islands)} islands from Firestore")

# Call the function during app startup
load_data_from_firestore()

# Add this new function for token verification
def verify_firebase_token(token):
    """Verify Firebase token and return the UID if valid"""
    try:
        if not token:
            logger.warning("No token provided for verification")
            return None
            
        logger.info("Attempting to verify Firebase token")
        
        # Verify the token
        decoded_token = firebase_auth.verify_id_token(token)
        
        # Get user UID from the token
        uid = decoded_token['uid']
        logger.info(f"Successfully verified Firebase token for user: {uid}")
        return uid
    except Exception as e:
        logger.error(f"Error verifying Firebase token: {e}")
        logger.exception("Token verification exception details:")  # This logs the full stack trace
        return None

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")
    
    # Look up the player ID from socket session
    try:
        session_ref = db.collection('socket_sessions').document(request.sid)
        session = session_ref.get()
        
        if session.exists:
            session_data = session.to_dict()
            player_id = session_data.get('player_id')
            
            # If this was a player, mark them as inactive
            if player_id and player_id in players:
                # Update player in Firestore and cache
                firestore_models.Player.update(player_id, active=False, last_update=time.time())
                if player_id in players:
                    players[player_id]['active'] = False
                    
                    # Broadcast that the player disconnected
                    emit('player_disconnected', {'id': player_id}, broadcast=True)
            
            # Delete the session mapping
            session_ref.delete()
        else:
            # Legacy fallback - directly use socket ID as player ID
            player_id = request.sid
            if player_id in players:
                # Update player in Firestore and cache
                firestore_models.Player.update(player_id, active=False, last_update=time.time())
                players[player_id]['active'] = False
                
                # Broadcast that the player disconnected
                emit('player_disconnected', {'id': player_id}, broadcast=True)
    except Exception as e:
        logger.error(f"Error handling disconnect: {e}")

@socketio.on('player_join')
def handle_player_join(data):
    # Get the Firebase token and UID from the request
    firebase_token = data.get('firebaseToken')
    claimed_firebase_uid = data.get('firebaseUid')
    
    # Use socket ID as default player ID
    player_id = request.sid

    logger.info(f"Player join data: {data}")
    
    # Initialize verified_uid to None by default
    verified_uid = None
    
    # If Firebase authentication is being used, verify the token
    if firebase_token and claimed_firebase_uid:
        verified_uid = verify_firebase_token(firebase_token)
        
        # Only use the Firebase UID if token verification succeeded
        if verified_uid and verified_uid == claimed_firebase_uid:
            logger.info(f"Authentication successful for Firebase user: {verified_uid}")
            # Use the Firebase UID instead of socket ID for persistent identity
            player_id = f"firebase_{verified_uid}"
        else:
            logger.warning(f"Firebase token verification failed. Using socket ID instead.")
    
    logger.info(f"New player joined: {player_id}")
    logger.info(f"Name: {data.get('name', 'Unknown')}")
    
    # Check if this player already exists in the database
    existing_player = firestore_models.Player.get(player_id)
    
    if existing_player:
        # Update the existing player's active status and socket ID
        logger.info(f"Existing player reconnected: {player_id}")
        
        # Store the socket ID mapping for this player
        session_mapping = {
            'player_id': player_id,
            'socket_id': request.sid,
            'last_update': time.time()
        }
        
        # Store mapping in a new collection
        db.collection('socket_sessions').document(request.sid).set(session_mapping)
        
        # Update player data
        player_data = {
            'active': True,
            'last_update': time.time(),
            'position': data.get('position', existing_player.get('position')),
            'rotation': data.get('rotation', existing_player.get('rotation')),
            'mode': data.get('mode', existing_player.get('mode'))
        }
        
        # Update in Firestore
        firestore_models.Player.update(player_id, **player_data)
        
        # Update cache
        players[player_id] = {**existing_player, **player_data}
    else:
        # Create new player entry with stats
        player_data = {
            'name': data.get('name', f'Sailor {player_id[:4]}'),
            'color': data.get('color', {'r': 0.3, 'g': 0.6, 'b': 0.8}),
            'position': data.get('position', {'x': 0, 'y': 0, 'z': 0}),
            'rotation': data.get('rotation', 0),
            'mode': data.get('mode', 'boat'),
            'last_update': time.time(),
            'fishCount': 0,
            'monsterKills': 0,
            'money': 0,
            'active': True,  # Mark as active when they join
            'firebase_uid': claimed_firebase_uid if verified_uid else None
        }
        
        # Create player in Firestore and cache the result
        player = firestore_models.Player.create(player_id, **player_data)
        players[player_id] = player
        
        # Store the socket ID mapping
        session_mapping = {
            'player_id': player_id,
            'socket_id': request.sid,
            'last_update': time.time()
        }
        db.collection('socket_sessions').document(request.sid).set(session_mapping)
    
    # Broadcast to all clients that a new player joined
    emit('player_joined', players[player_id], broadcast=True)
    
    # Send existing ACTIVE players to the new player
    active_players = [p for p in players.values() if p.get('active', False)]
    emit('all_players', active_players)
    
    # Send all islands to the new player
    emit('all_islands', list(islands.values()))
    
    # Send recent messages to the new player
    recent_messages = firestore_models.Message.get_recent_messages(limit=20)
    emit('chat_history', recent_messages)
    
    # Send leaderboard data to the new player
    emit('leaderboard_update', firestore_models.Player.get_combined_leaderboard())

@socketio.on('player_update')
def handle_player_update(data):
    logger.info(f"Player update data: {data}")
    socket_id = request.sid
    
    # Find the player ID associated with this socket
    try:
        session_ref = db.collection('socket_sessions').document(socket_id)
        session = session_ref.get()
        
        if session.exists:
            player_id = session.to_dict().get('player_id')
        else:
            # Legacy fallback
            player_id = socket_id
    except Exception as e:
        logger.error(f"Error finding player for socket {socket_id}: {e}")
        return
    
    # Ensure player exists
    if player_id not in players:
        return
    
    current_time = time.time()
    
    # Update in-memory cache immediately
    for key, value in data.items():
        if key in ['position', 'rotation', 'mode']:
            players[player_id][key] = value
    
    players[player_id]['last_update'] = current_time
    
    # Throttle database updates (only update every DB_UPDATE_INTERVAL seconds)
    if current_time - last_db_update[player_id] > DB_UPDATE_INTERVAL:
        last_db_update[player_id] = current_time
        
        # Only update necessary fields in Firestore
        update_data = {
            'position': players[player_id]['position'],
            'rotation': players[player_id]['rotation'],
            'mode': players[player_id]['mode'],
            'last_update': current_time
        }
        
        firestore_models.Player.update(player_id, **update_data)
    
    # Broadcast update to all other clients
    emit('player_moved', {
        'id': player_id,
        'position': players[player_id]['position'],
        'rotation': players[player_id]['rotation'],
        'mode': players[player_id]['mode']
    }, broadcast=True, include_self=False)

@socketio.on('player_action')
def handle_player_action(data):
    player_id = request.sid
    action_type = data.get('type')
    
    # Ensure player exists
    if player_id not in players:
        return
    
    if action_type == 'fish_caught':
        # Increment fish count
        if 'fishCount' not in players[player_id]:
            players[player_id]['fishCount'] = 0
        players[player_id]['fishCount'] += 1
        
        # Update player in Firestore
        firestore_models.Player.update(player_id, 
                                     fishCount=players[player_id]['fishCount'])
        
        # Broadcast achievement to all players
        emit('player_achievement', {
            'id': player_id,
            'name': players[player_id]['name'],
            'achievement': 'Caught a fish!',
            'fishCount': players[player_id]['fishCount']
        }, broadcast=True)
        
        # Update leaderboard
        emit('leaderboard_update', 
             firestore_models.Player.get_combined_leaderboard(), 
             broadcast=True)
    
    elif action_type == 'monster_killed':
        # Increment monster kills
        if 'monsterKills' not in players[player_id]:
            players[player_id]['monsterKills'] = 0
        players[player_id]['monsterKills'] += 1
        
        # Update player in Firestore
        firestore_models.Player.update(player_id, 
                                     monsterKills=players[player_id]['monsterKills'])
        
        # Broadcast achievement to all players
        emit('player_achievement', {
            'id': player_id,
            'name': players[player_id]['name'],
            'achievement': 'Defeated a sea monster!',
            'monsterKills': players[player_id]['monsterKills']
        }, broadcast=True)
        
        # Update leaderboard
        emit('leaderboard_update', 
             firestore_models.Player.get_combined_leaderboard(), 
             broadcast=True)
    
    elif action_type == 'money_earned':
        amount = data.get('amount', 0)
        
        # Add money
        if 'money' not in players[player_id]:
            players[player_id]['money'] = 0
        players[player_id]['money'] += amount
        
        # Update player in Firestore
        firestore_models.Player.update(player_id, 
                                     money=players[player_id]['money'])
        
        # Broadcast achievement to all players
        emit('player_achievement', {
            'id': player_id,
            'name': players[player_id]['name'],
            'achievement': f'Earned {amount} coins!',
            'money': players[player_id]['money']
        }, broadcast=True)
        
        # Update leaderboard
        emit('leaderboard_update', 
             firestore_models.Player.get_combined_leaderboard(), 
             broadcast=True)

@socketio.on('chat_message')
def handle_chat_message(data):
    player_id = request.sid
    content = data.get('content', '').strip()
    
    # Validate message
    if not content or len(content) > 500:
        return
    
    # Create message in Firestore
    message = firestore_models.Message.create(
        player_id,
        content,
        message_type='global'
    )
    
    if message:
        # Broadcast message to all clients
        emit('chat_message', message, broadcast=True)

# API endpoints
@app.route('/api/players', methods=['GET'])
def get_players():
    """Get all active players"""
    active_players = [p for p in players.values() if p.get('active', False)]
    return jsonify(active_players)

@app.route('/api/players/<player_id>', methods=['GET'])
def get_player(player_id):
    """Get a specific player"""
    player = firestore_models.Player.get(player_id)
    if player:
        return jsonify(player)
    return jsonify({'error': 'Player not found'}), 404

@app.route('/api/islands', methods=['GET'])
def get_islands():
    """Get all islands"""
    return jsonify(list(islands.values()))

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """Get the combined leaderboard"""
    return jsonify(firestore_models.Player.get_combined_leaderboard())

@app.route('/api/messages', methods=['GET'])
def get_messages():
    """Get recent chat messages"""
    message_type = request.args.get('type', 'global')
    limit = int(request.args.get('limit', 50))
    messages = firestore_models.Message.get_recent_messages(limit=limit, message_type=message_type)
    return jsonify(messages)

@app.route('/api/admin/create_island', methods=['POST'])
def create_island():
    """Admin endpoint to create an island"""
    data = request.json
    
    # Basic validation
    if not data or 'position' not in data:
        return jsonify({'error': 'Invalid island data'}), 400
    
    # Generate island ID
    island_id = f"island_{int(time.time())}"
    
    # Create island in Firestore
    island = firestore_models.Island.create(island_id, **data)
    
    # Add to cache
    islands[island_id] = island
    
    # Broadcast to all clients
    socketio.emit('island_created', island)
    
    return jsonify(island)

# Serve static files
@app.route('/files/<path:filename>')
def serve_static_file(filename):
    """
    Serve static files from the static directory
    Access files via: http://localhost:5000/files/models/boat.glb
    """
    try:
        logger.info(f"Serving static file: {filename}")
        response = send_from_directory(STATIC_FILES_DIR, filename)
        
        # Add CORS headers if needed
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        
        # Log the MIME type for debugging
        logger.info(f"Serving {filename} with MIME type: {response.mimetype}")
        
        return response
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        return jsonify({
            'success': False,
            'error': f"File not found or error: {str(e)}"
        }), 404

# Add an info endpoint to help with debugging file paths
@app.route('/file-system-info')
def file_system_info():
    """Return information about the static file system configuration"""
    files = []
    
    # Walk through the static directory and list all files
    for root, dirs, filenames in os.walk(STATIC_FILES_DIR):
        for filename in filenames:
            # Get relative path
            rel_path = os.path.relpath(os.path.join(root, filename), STATIC_FILES_DIR)
            files.append({
                'path': rel_path,
                'url': f"/files/{rel_path.replace(os.sep, '/')}",
                'mime': mimetypes.guess_type(filename)[0]
            })
            
    return jsonify({
        'static_dir': STATIC_FILES_DIR,
        'files': files,
        'mime_types': {
            '.glb': mimetypes.guess_type('model.glb')[0],
            '.gltf': mimetypes.guess_type('model.gltf')[0],
            '.png': mimetypes.guess_type('image.png')[0],
            '.jpg': mimetypes.guess_type('image.jpg')[0],
            '.mp3': mimetypes.guess_type('audio.mp3')[0]
        }
    })

if __name__ == '__main__':
    # Run the Socket.IO server with debug and reloader enabled
    socketio.run(app, host='0.0.0.0', port=5001, debug=True, use_reloader=True) 