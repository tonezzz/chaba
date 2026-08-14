#!/usr/bin/env python3
"""
Auto-KB Processing Script
Analyzes KB review content and creates/updates KB entries automatically.
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Configuration
KB_DIR = Path("/home/tony/CascadeProjects/chaba-kbman/docs/kb")
KB_REVIEW_FILE = Path("/tmp/kb-review-content.txt")

# Exclude general guide files and recent migration files from redundancy checks
EXCLUDE_FILES = {'mddb-user-guide.md', 'ssot-documentation-standards.md', 
                 'documentation-search.md', 'global-rules-testing-guide.md',
                 'wind-forecast.md', 'playlive-authentication.md',
                 'kb-migration-summary-2026-08-13.md', 'meta-backup-plan-legacy.md',
                 'ai-context-tech-stack.md', 'ai-context-general-knowledge.md',
                 'mddb-implementation-complete.md', 'mddb-migration-strategy.md',
                 'mddb-future-improvements.md', 'mddb-migration-final-status.md'}

# KB-worthy triggers
KB_TRIGGERS = [
    "significant bug fixes", "data corruption", "security vulnerabilities",
    "new patterns", "workarounds", "best practices",
    "new systems", "integrations", "technologies",
    "configuration optimizations", "performance improvements",
    "language-specific", "encoding issues",
    "root cause analyses", "complex problems",
    "reusable patterns", "conventions"
]

def read_kb_review():
    """Read KB review content from file or stdin"""
    if KB_REVIEW_FILE.exists():
        return KB_REVIEW_FILE.read_text()
    elif len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    else:
        return sys.stdin.read()

def analyze_kb_worthiness(content):
    """Analyze content for KB-worthiness"""
    content_lower = content.lower()
    triggers_found = []
    
    for trigger in KB_TRIGGERS:
        if trigger in content_lower:
            triggers_found.append(trigger)
    
    return triggers_found

def extract_kb_facts(content):
    """Extract individual KB facts from content"""
    # Split by numbered list items with bold text
    facts = re.split(r'\n\d+\.\s*\*\*', content)
    facts = [f.strip() for f in facts if f.strip()]
    
    # Clean up each fact
    cleaned_facts = []
    for fact in facts:
        # Remove the header line and extract the actual content
        lines = fact.split('\n')
        if len(lines) > 1:
            # Take content after the header
            fact_content = '\n'.join(lines[1:]).strip()
        else:
            fact_content = lines[0].strip()
        
        # Remove trailing colons and extra whitespace
        fact_content = re.sub(r':\s*$', '', fact_content)
        fact_content = fact_content.strip()
        
        # Remove the closing bold if present
        fact_content = re.sub(r'\*\*:\s*', ': ', fact_content)
        
        # Skip session context lines and header lines
        if (fact_content.startswith("Session context:") or 
            fact_content.startswith("KB-worthy facts") or
            len(fact_content) < 50):  # Minimum length threshold
            continue
            
        cleaned_facts.append(fact_content)
    
    return cleaned_facts

def check_redundancy(fact, existing_entries):
    """Check if fact overlaps with existing KB entries"""
    fact_lower = fact.lower()
    
    # Extract the main topic from the fact (before the colon)
    topic_match = re.match(r'([A-Z][^:]+):', fact)
    if topic_match:
        topic = topic_match.group(1).strip().lower()
    else:
        return None  # Can't determine topic, assume not redundant
    
    for entry_file in existing_entries:
        # Skip general guide files and unrelated files
        if entry_file.name in EXCLUDE_FILES:
            continue
            
        entry_content = entry_file.read_text().lower()
        
        # If it's the migration summary, check if it covers the topic comprehensively
        if entry_file.name == 'kb-migration-summary-2026-08-13.md':
            # Check if the topic is mentioned in the migration summary
            if topic in entry_content:
                # Check if there's substantial coverage (multiple mentions)
                topic_count = entry_content.count(topic)
                if topic_count >= 2:  # If mentioned multiple times, it's well covered
                    return entry_file.name
        
        # Check if the topic appears in the entry title or first section
        entry_title = entry_file.name.lower().replace('-', ' ')
        entry_first_section = entry_content.split('\n')[0] if entry_content else ""
        
        # Check for exact topic match in title or first section
        if (topic in entry_title or 
            topic in entry_first_section):
            
            # Additional check: require high content similarity
            fact_words = set(re.findall(r'\b\w{5,}\b', fact_lower))
            entry_words = set(re.findall(r'\b\w{5,}\b', entry_content))
            
            # If very high word overlap, consider it redundant
            overlap = fact_words & entry_words
            if len(overlap) >= 6:  # Require at least 6 overlapping longer words
                return entry_file.name
    
    return None

def generate_kb_entry_title(fact):
    """Generate a meaningful title from the fact"""
    # Extract the key topic from the fact (text before the colon)
    topic_match = re.match(r'([A-Z][^:]+):', fact)
    if topic_match:
        topic = topic_match.group(1).strip()
    else:
        # Fallback to first meaningful phrase
        first_sentence = re.split(r'[.!?]', fact)[0]
        words = first_sentence.split()
        topic = " ".join([w for w in words if len(w) > 3][:4])
    
    # Clean up the topic
    topic = re.sub(r'\*\*', '', topic)  # Remove bold markers
    topic = re.sub(r'[^\w\s-]', '', topic)  # Remove special chars
    topic = re.sub(r'\s+', ' ', topic).strip()  # Normalize spaces
    
    return topic.title()

def create_kb_entry(fact, session_context=""):
    """Create a KB entry from a fact"""
    title = generate_kb_entry_title(fact)
    timestamp = datetime.now().strftime("%Y-%m-%d")
    filename = f"{title.lower().replace(' ', '-')}-{timestamp}.md"
    filepath = KB_DIR / filename
    
    # Parse the fact for better structure
    # Look for patterns like "Topic:** Description"
    fact_parts = re.split(r'\*\*:\s*', fact, maxsplit=1)
    if len(fact_parts) == 2:
        topic = fact_parts[0].strip()
        description = fact_parts[1].strip()
    else:
        topic = title
        description = fact
    
    # Clean up the topic and description
    topic = re.sub(r'\*\*', '', topic)
    description = re.sub(r'\*\*', '', description)
    
    entry_content = f"""# {title}

## What it is

{topic}

## Context/Background

**Date:** {timestamp}
**Session Context:** {session_context}

## Key Details

### Technical Details
{description}

### Implementation
- **Status:** Documented
- **Date:** {timestamp}
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
"""
    
    return filepath, entry_content

def main():
    """Main processing function"""
    print("🔍 Auto-KB Processing Started")
    
    # Read KB review content
    content = read_kb_review()
    if not content:
        print("❌ No KB review content found")
        return
    
    print(f"📝 KB review content loaded ({len(content)} characters)")
    
    # Analyze KB-worthiness
    triggers = analyze_kb_worthiness(content)
    print(f"🎯 KB-worthy triggers found: {triggers}")
    
    # Extract individual facts
    facts = extract_kb_facts(content)
    print(f"📋 Extracted {len(facts)} KB facts")
    
    # Get existing KB entries
    existing_entries = list(KB_DIR.glob("*.md"))
    print(f"📁 Found {len(existing_entries)} existing KB entries")
    
    # Process each fact
    entries_created = []
    entries_skipped = []
    
    for i, fact in enumerate(facts, 1):
        print(f"\n🔄 Processing fact {i}/{len(facts)}")
        print(f"   Content: {fact[:80]}...")
        
        # Check redundancy
        redundant_file = check_redundancy(fact, existing_entries)
        if redundant_file:
            print(f"   ⚠️  Skipped (redundant with: {redundant_file})")
            entries_skipped.append((fact, redundant_file))
            continue
        
        # Create KB entry
        try:
            filepath, entry_content = create_kb_entry(fact)
            filepath.write_text(entry_content)
            print(f"   ✅ Created: {filepath.name}")
            entries_created.append(filepath.name)
            
            # Add newly created file to exclude list for subsequent checks
            EXCLUDE_FILES.add(filepath.name)
            
        except Exception as e:
            print(f"   ❌ Error creating entry: {e}")
    
    # Summary
    print(f"\n📊 Processing Summary:")
    print(f"   ✅ Entries created: {len(entries_created)}")
    print(f"   ⚠️  Entries skipped (redundant): {len(entries_skipped)}")
    
    if entries_created:
        print(f"\n📁 Created entries:")
        for entry in entries_created:
            print(f"   - {entry}")
    
    if entries_skipped:
        print(f"\n⚠️  Skipped entries (redundant):")
        for fact, filename in entries_skipped:
            print(f"   - {filename}: {fact[:60]}...")
    
    print(f"\n✅ Auto-KB Processing Complete")

if __name__ == "__main__":
    main()