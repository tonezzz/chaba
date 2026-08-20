---
category: operations
---

# Key Details

### Technical Details
- **Git Operations**: Full git status, diff, commit, and history support
- **Duplicate Detection**: GDrive naming conflict identification (e.g., `README (1).md`)
- **Frontmatter Validation**: YAML format and required field checking
- **Session Management**: Current context and active projects tracking
- **Changelog Tracking**: Automatic change logging with timestamps
- **Performance**: Git operations on GDrive mount require 120s timeout

### Component Architecture

#### 1. GitManager (`workflow/git_manager.py`)
**Purpose**: Manages git operations for KB workflow

**Responsibilities**:
- Git status checking with changed file detection
- Git diff operations for specific files or all changes
- File staging and committing with error handling
- Commit history retrieval with metadata
- Branch management and remote operations

**Key Methods**:
- `get_status()` - Get git status (changed files, total changes)
- `get_diff(file_path)` - Get git diff (specific file or all)
- `add_file(file_path)` - Stage file for commit
- `commit(message)` - Commit staged changes
- `get_recent_commits(limit)` - Get commit history
- `get_branch()` - Get current git branch
- `pull()` / `push()` - Remote operations

**Configuration**:
```python
KB_PATH = "/home/tony/GoogleDrive/Tony AI/KB"
GIT_TIMEOUT = 120  # Increased for GDrive mount operations
```

#### 2. DuplicateDetector (`workflow/duplicate_detector.py`)
**Purpose**: Detects GDrive duplicate files (naming conflicts)

**Responsibilities**:
- GDrive duplicate pattern detection (`filename (1).md`)
- Duplicate summary and reporting
- Affected file grouping
- Original file existence checking

**Key Methods**:
- `find_duplicates()` - Find all duplicate files
- `get_duplicate_summary()` - Get duplicate statistics
- `has_duplicates()` - Check if duplicates exist
- `get_duplicate_report()` - Human-readable report

**Pattern Matching**:
```python
# GDrive duplicate pattern
DUPLICATE_PATTERN = re.compile(r'^(.+?)\s*\(\d+\)(\.[^.]+)$')
# Matches: README (1).md, document (2).txt, etc.
```

#### 3. KBValidator (`workflow/kb_validator.py`)
**Purpose**: Validates KB entries and frontmatter

**Responsibilities**:
- Frontmatter validation with YAML parsing
- Required field checking (title, date, tags, status)
- Date format validation (YYYY-MM-DD)
- Status value validation (active, completed, backlog)
- Frontmatter generation for new entries
- Lenient validation (skips templates, historical entries)

**Key Methods**:
- `validate_frontmatter(content, require_frontmatter)` - Validate frontmatter
- `validate_file(file_path, require_frontmatter)` - Validate specific file
- `validate_kb(require_frontmatter)` - Validate all KB files
- `generate_frontmatter(title, tags, status)` - Generate frontmatter

**Validation Rules**:
```python
REQUIRED_FIELDS = ['title', 'date', 'tags', 'status']
VALID_STATUSES = ['active', 'completed', 'backlog']
DATE_FORMAT = '%Y-%m-%d'

# Skip patterns
SKIP_PATTERNS = ['templates/', 'changes.md', date-based filenames]
```

#### 4. SessionManager (`workflow/session_manager.py`)
**Purpose**: Manages KB session state and context

**Responsibilities**:
- Current context reading/updating
- Active projects reading/updating
- Changelog entry management with timestamps
- Session state tracking
- File existence checking

**Key Methods**:
- `read_current_context()` - Read current context file
- `update_current_context(content)` - Update current context
- `read_active_projects()` - Read active projects file
- `update_active_projects(content)` - Update active projects
- `add_changelog_entry(entry)` - Add changelog entry
- `get_session_state()` - Get session state

**File Locations**:
```python
CURRENT_CONTEXT_FILE = "current-context.md"
ACTIVE_PROJECTS_FILE = "active-projects.md"
CHANGELOG_FILE = "meta/changelog.md"
```

#### 5. WorkflowCoordinator (`workflow/coordinator.py`)
**Purpose**: Coordinates all KB workflow components

**Responsibilities**:
- kb-start.sh equivalent workflow checks
- kb-end.sh equivalent workflow operations
- Issue collection and reporting
- KB entry creation with proper formatting
- Component integration and orchestration

**Key Methods**:
- `kb_start_check()` - Complete workflow check before work
- `kb_end_commit(summary)` - Commit changes and update changelog
- `resolve_duplicate(duplicate_path, action)` - Resolve duplicate files
- `create_kb_entry(title, content, tags, status)` - Create KB entry

**Workflow Check Logic**:
```python
ready_for_work = (
    not git_status['has_changes'] and
    duplicate_summary['total_duplicates'] == 0 and
    validation_result['invalid_files'] == 0
)
```

