#!/usr/bin/env python3
"""Migrate old Yomi files to MDDB for archival"""
import os
import json
import requests
from datetime import datetime

YOMI_DIR = "/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi-archive"
MDBB_SERVER = "http://localhost:9001"
COLLECTION = "yomi-archive"

def migrate_conversations():
    """Migrate conversations.json to MDDB"""
    conversations_file = os.path.join(YOMI_DIR, "conversations.json")
    
    if not os.path.exists(conversations_file):
        print(f"❌ conversations.json not found at {conversations_file}")
        return False
    
    with open(conversations_file, 'r') as f:
        data = json.load(f)
    
    # Create markdown content from conversations
    content_md = f"# Yomi Conversations Archive\n\n"
    content_md += f"**Generated At**: {data.get('generatedAt', 'Unknown')}\n\n"
    content_md += f"**Total Conversations**: {len(data.get('conversations', []))}\n\n"
    content_md += "## Conversation List\n\n"
    
    for conv in data.get('conversations', []):
        content_md += f"### {conv.get('name', 'Unknown')} ({conv.get('id', 'Unknown')})\n"
        content_md += f"- **Category**: {conv.get('category', 'Unknown')}\n"
        content_md += f"- **Unread**: {conv.get('unread', 0)}\n"
        content_md += f"- **Last Message**: {conv.get('lastMessageTime', 'Unknown')}\n"
        content_md += f"- **Summary**: {conv.get('summary', 'No summary')}\n"
        content_md += f"- **Is Group**: {conv.get('isGroup', False)}\n\n"
    
    payload = {
        "name": "add_document",
        "arguments": {
            "collection": COLLECTION,
            "key": "conversations",
            "lang": "en",
            "content_md": content_md,
            "meta": {
                "title": ["Yomi Conversations Metadata"],
                "source": "yomi-archive",
                "type": "conversations",
                "archived_date": datetime.now().isoformat()
            }
        }
    }
    
    try:
        response = requests.post(f"{MDBB_SERVER}/tools/call", json=payload)
        response.raise_for_status()
        result = response.json()
        print(f"✅ Conversations migrated successfully")
        return True
    except Exception as e:
        print(f"❌ Error migrating conversations: {e}")
        return False

def migrate_messages():
    """Migrate individual message files to MDDB"""
    messages_dir = os.path.join(YOMI_DIR, "messages")
    
    if not os.path.exists(messages_dir):
        print(f"❌ messages directory not found at {messages_dir}")
        return False
    
    message_files = [f for f in os.listdir(messages_dir) if f.endswith('.json')]
    total_files = len(message_files)
    print(f"📁 Found {total_files} message files to migrate")
    
    success_count = 0
    
    for filename in message_files:
        filepath = os.path.join(messages_dir, filename)
        conversation_id = filename[:-5]  # Remove .json
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Create markdown content from messages
        content_md = f"# Messages: {conversation_id}\n\n"
        content_md += f"**Generated At**: {data.get('generatedAt', 'Unknown')}\n\n"
        content_md += f"**Total Messages**: {len(data.get('messages', []))}\n\n"
        content_md += "## Message History\n\n"
        
        for msg in data.get('messages', []):
            content_md += f"### {msg.get('createdTime', 'Unknown')} - {msg.get('fromName', 'Unknown')}\n"
            content_md += f"**From**: {msg.get('from', 'Unknown')}\n"
            if msg.get('text'):
                content_md += f"**Text**: {msg['text']}\n"
            if msg.get('mediaType'):
                content_md += f"**Media**: {msg['mediaType']}\n"
            content_md += f"**E2EE**: {msg.get('e2eeDecrypted', False)}\n"
            content_md += f"**Verified**: {msg.get('e2eeIntegrityVerified', False)}\n\n"
        
        payload = {
            "name": "add_document",
            "arguments": {
                "collection": COLLECTION,
                "key": f"messages-{conversation_id}",
                "lang": "en",
                "content_md": content_md,
                "meta": {
                    "title": [f"Messages - {conversation_id}"],
                    "source": "yomi-archive",
                    "type": "messages",
                    "conversation_id": conversation_id,
                    "archived_date": datetime.now().isoformat()
                }
            }
        }
        
        try:
            response = requests.post(f"{MDBB_SERVER}/tools/call", json=payload)
            response.raise_for_status()
            print(f"✅ Migrated: {conversation_id}")
            success_count += 1
        except Exception as e:
            print(f"❌ Error migrating {conversation_id}: {e}")
    
    print(f"\n🎉 Messages migration completed!")
    print(f"📊 Files migrated: {success_count}/{total_files}")
    return success_count == total_files

def main():
    print("🚀 Starting Yomi to MDDB migration...")
    print(f"📁 Source: {YOMI_DIR}")
    print(f"🎯 Target: {MDBB_SERVER} (collection: {COLLECTION})")
    print()
    
    # Test MDDB connection
    try:
        response = requests.post(f"{MDBB_SERVER}/tools/call", 
                               json={"name": "add_document", "arguments": {
                                   "collection": COLLECTION, "key": "test-connection", 
                                   "lang": "en", "content_md": "Connection test"
                               }})
        if response.status_code == 200:
            print("✅ MDDB connection successful")
            # Clean up test document
            requests.post(f"{MDBB_SERVER}/tools/call",
                        json={"name": "delete_document", "arguments": {
                            "collection": COLLECTION, "key": "test-connection", "lang": "en"
                        }})
        else:
            print("❌ MDDB connection failed")
            return
    except Exception as e:
        print(f"❌ Cannot connect to MDDB: {e}")
        return
    
    print()
    
    # Migrate conversations
    print("📄 Migrating conversations.json...")
    conv_success = migrate_conversations()
    
    print()
    
    # Migrate messages
    print("📨 Migrating messages directory...")
    msg_success = migrate_messages()
    
    print()
    print("🎉 Migration completed!")
    print(f"📊 Results:")
    print(f"   - Conversations: {'✅' if conv_success else '❌'}")
    print(f"   - Messages: {'✅' if msg_success else '❌'}")
    
    if conv_success and msg_success:
        print(f"\n✅ All Yomi data successfully archived to MDDB collection '{COLLECTION}'")
        print(f"🔗 Access via MDDB Panel: http://tony-omen.local:3002/")
    else:
        print(f"\n⚠️  Some migrations failed. Please check the errors above.")

if __name__ == "__main__":
    main()