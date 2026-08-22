#!/usr/bin/env python3
"""Migrate Yomi LINE conversations to MDDB using MCP API"""
import os
import json
import requests
from datetime import datetime

YOMI_DIR = "/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi"
MDBB_SERVER = "http://localhost:9001"

def get_collection(category):
    """Determine collection based on conversation category"""
    category_map = {
        "Personal": "yomi-personal",
        "Official": "yomi-official", 
        "Group": "yomi-groups",
        "Work": "yomi-work",
        "default": "yomi-general"
    }
    return category_map.get(category, "yomi-general")

def format_conversation_markdown(conversation, messages):
    """Format conversation and messages as markdown"""
    md_content = f"# {conversation['name']}\n\n"
    
    # Add metadata
    md_content += f"**Conversation ID:** `{conversation['id']}`\n"
    md_content += f"**Category:** {conversation.get('category', 'Unknown')}\n"
    md_content += f"**Group:** {'Yes' if conversation.get('isGroup') else 'No'}\n"
    md_content += f"**Unread Messages:** {conversation.get('unread', 0)}\n"
    
    if conversation.get('summary'):
        md_content += f"**Summary:** {conversation['summary']}\n"
    
    md_content += f"\n---\n\n## Messages\n\n"
    
    # Add messages
    for msg in messages:
        # Handle missing timestamps
        created_time = msg.get('createdTime')
        if created_time:
            timestamp = datetime.fromtimestamp(created_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
        else:
            timestamp = "Unknown time"
        
        sender = msg.get('fromName', 'Unknown')
        text = msg.get('text', '')
        
        md_content += f"### {sender} - {timestamp}\n\n"
        md_content += f"{text}\n\n"
    
    return md_content

def migrate_conversation(conversation, messages_data):
    """Migrate a single conversation to MDDB"""
    conv_id = conversation['id']
    collection = get_collection(conversation.get('category'))
    
    # Format as markdown
    content_md = format_conversation_markdown(conversation, messages_data)
    
    payload = {
        "name": "add_document",
        "arguments": {
            "collection": collection,
            "key": conv_id,
            "lang": "th",  # Thai language for LINE conversations
            "content_md": content_md,
            "meta": {
                "title": conversation['name'],
                "source": "yomi-line",
                "category": conversation.get('category', 'Unknown'),
                "is_group": conversation.get('isGroup', False),
                "unread_count": conversation.get('unread', 0),
                "message_count": len(messages_data),
                "last_message_time": conversation.get('lastMessageTime'),
                "migrated_at": datetime.now().isoformat()
            }
        }
    }
    
    try:
        response = requests.post(f"{MDBB_SERVER}/tools/call", json=payload)
        response.raise_for_status()
        return True, collection
    except Exception as e:
        print(f"❌ Error migrating {conv_id}: {e}")
        return False, collection

def main():
    # Load conversations metadata
    conversations_file = os.path.join(YOMI_DIR, "conversations.json")
    with open(conversations_file, 'r') as f:
        conv_data = json.load(f)
    
    conversations = conv_data.get('conversations', [])
    print(f"📁 Found {len(conversations)} conversations to migrate")
    
    # Load messages
    messages_dir = os.path.join(YOMI_DIR, "messages")
    message_files = [f for f in os.listdir(messages_dir) if f.endswith('.json')]
    print(f"📄 Found {len(message_files)} message files")
    
    # Build message lookup
    messages_lookup = {}
    for msg_file in message_files:
        msg_path = os.path.join(messages_dir, msg_file)
        with open(msg_path, 'r') as f:
            msg_data = json.load(f)
            conv_id = msg_file.replace('.json', '')
            messages_lookup[conv_id] = msg_data.get('messages', [])
    
    # Migrate conversations
    success_count = 0
    collection_counts = {}
    
    for conversation in conversations:
        conv_id = conversation['id']
        
        # Skip if no messages found
        if conv_id not in messages_lookup:
            print(f"⚠️  No messages found for {conversation['name']} ({conv_id})")
            continue
        
        messages = messages_lookup[conv_id]
        print(f"📄 Migrating: {conversation['name']} ({len(messages)} messages)", end=" ... ")
        
        success, collection = migrate_conversation(conversation, messages)
        
        if success:
            print(f"✅ ({collection})")
            success_count += 1
            collection_counts[collection] = collection_counts.get(collection, 0) + 1
        else:
            print("❌")
    
    print(f"\n🎉 Yomi migration completed!")
    print(f"📊 Conversations migrated: {success_count}/{len(conversations)}")
    print(f"📁 Collection breakdown:")
    for collection, count in collection_counts.items():
        print(f"   - {collection}: {count}")

if __name__ == "__main__":
    main()