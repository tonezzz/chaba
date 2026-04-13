// Skill Creator UI - Standalone JavaScript
// This file contains all client-side logic to avoid template literal conflicts

let currentSkill = null;
let currentMarkdown = '';
let currentStatus = 'draft';
let workflowHistory = ['Created as draft'];

function setExample(text) {
    document.getElementById('skillInput').value = text;
    document.getElementById('skillInput').focus();
}

function setRevision(text) {
    document.getElementById('revisionInput').value = text;
    document.getElementById('revisionInput').focus();
}

function setStatus(status, text) {
    const el = document.getElementById('status');
    el.className = 'status ' + status;
    el.textContent = text;
}

async function createSkill() {
    const input = document.getElementById('skillInput').value.trim();
    if (!input) return;
    
    setStatus('processing', 'Interpreting...');
    document.getElementById('createBtn').disabled = true;
    
    try {
        const response = await fetch('/api/skills/interpret', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ input })
        });
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        currentSkill = data.config;
        currentMarkdown = data.markdown;
        
        // Show config
        const configTable = document.getElementById('configTable');
        const triggers = data.config.trigger_phrases.map(function(t) { 
            return '<code>' + t + '</code>'; 
        }).join(', ');
        
        configTable.innerHTML = 
            '<tr><td>Name</td><td><code>' + data.config.skill_name + '</code></td></tr>' +
            '<tr><td>Category</td><td>' + data.config.category + '</td></tr>' +
            '<tr><td>Handler</td><td>' + data.config.handler_type + '</td></tr>' +
            '<tr><td>Triggers</td><td>' + triggers + '</td></tr>' +
            '<tr><td>Priority</td><td>' + data.config.priority + '</td></tr>';
        
        // Show markdown preview
        document.getElementById('markdownPreview').textContent = data.markdown;
        
        // Show preview box
        document.getElementById('previewBox').style.display = 'block';
        document.getElementById('revisionSection').classList.remove('active');
        document.getElementById('resultMessage').textContent = '';
        
        // Show workflow section
        document.getElementById('workflowSection').style.display = 'block';
        updateWorkflowButtons();
        
        setStatus('ready', 'Skill interpreted! Review and save.');
        
    } catch (error) {
        setStatus('error', 'Error: ' + error.message);
        console.error('Error:', error);
    } finally {
        document.getElementById('createBtn').disabled = false;
    }
}

async function reviseSkill() {
    const revision = document.getElementById('revisionInput').value.trim();
    if (!revision || !currentSkill) return;
    
    setStatus('processing', 'Revising...');
    
    try {
        const response = await fetch('/api/skills/revise', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                markdown: currentMarkdown,
                revision: revision,
                config: currentSkill
            })
        });
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        currentMarkdown = data.markdown;
        document.getElementById('markdownPreview').textContent = data.markdown;
        
        // Show Thai panel if revision mentions Thai
        if (revision.toLowerCase().includes('thai')) {
            document.getElementById('thaiPanel').style.display = 'block';
        }
        
        document.getElementById('resultMessage').innerHTML = 
            '<span class="success">Revision applied</span>';
        setStatus('ready', 'Skill revised!');
        
    } catch (error) {
        setStatus('error', 'Error: ' + error.message);
        console.error('Error:', error);
    }
}

async function saveToWiki() {
    if (!currentSkill || !currentMarkdown) return;
    
    setStatus('processing', 'Saving...');
    
    try {
        const response = await fetch('/api/skills/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: currentSkill.skill_name,
                markdown: currentMarkdown,
                config: currentSkill
            })
        });
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        document.getElementById('resultMessage').innerHTML = 
            '<span class="success">Saved to ' + data.saved_to + '</span>';
        setStatus('success', 'Saved!');
        
    } catch (error) {
        setStatus('error', 'Error: ' + error.message);
        console.error('Error:', error);
    }
}

// Thai Configuration Functions
function applyThaiConfig() {
    const thaiName = document.getElementById('thaiName').value.trim();
    const thaiTriggers = document.getElementById('thaiTriggers').value.trim();
    
    if (!thaiName && !thaiTriggers) {
        alert('Please enter Thai name or trigger phrases');
        return;
    }
    
    let thaiSection = '\n\n## Thai Language Support\n';
    if (thaiName) {
        thaiSection += '- **Thai Name**: ' + thaiName + '\n';
    }
    if (thaiTriggers) {
        const triggers = thaiTriggers.split(',').map(function(t) { 
            return t.trim(); 
        }).filter(function(t) { 
            return t; 
        });
        const triggerList = triggers.map(function(t) { 
            return '  - "' + t + '"'; 
        }).join('\n');
        thaiSection += '- **Thai Triggers**:\n' + triggerList + '\n';
    }
    thaiSection += '- **Language**: th\n';
    
    currentMarkdown += thaiSection;
    document.getElementById('markdownPreview').textContent = currentMarkdown;
    
    // Also update languages in metadata
    currentMarkdown = currentMarkdown.replace(
        '- **Languages**: en',
        '- **Languages**: en, th'
    );
    document.getElementById('markdownPreview').textContent = currentMarkdown;
    
    document.getElementById('resultMessage').innerHTML = 
        '<span class="success">Thai configuration applied</span>';
}

// Show Thai panel when revision mentions Thai
function showRevision() {
    document.getElementById('revisionSection').classList.add('active');
    document.getElementById('thaiPanel').style.display = 'block';
    document.getElementById('revisionInput').focus();
}

// Workflow Functions
function updateStatus(newStatus) {
    currentStatus = newStatus;
    workflowHistory.push(newStatus);
    
    // Update badges
    document.querySelectorAll('.status-badge').forEach(function(badge) {
        badge.classList.remove('active');
        if (badge.dataset.status === newStatus) {
            badge.classList.add('active');
        }
    });
    
    // Update history
    document.getElementById('historyText').textContent = workflowHistory.join(' → ');
    
    updateWorkflowButtons();
    
    document.getElementById('resultMessage').innerHTML = 
        '<span class="success">Status updated to: ' + newStatus + '</span>';
}

function updateWorkflowButtons() {
    const btnReview = document.getElementById('btnReview');
    const btnApprove = document.getElementById('btnApprove');
    const btnReject = document.getElementById('btnReject');
    const btnReady = document.getElementById('btnReady');
    
    // Hide all first
    if (btnReview) btnReview.style.display = 'none';
    if (btnApprove) btnApprove.style.display = 'none';
    if (btnReject) btnReject.style.display = 'none';
    if (btnReady) btnReady.style.display = 'none';
    
    // Show based on current status
    if (currentStatus === 'draft' && btnReview) {
        btnReview.style.display = 'inline-block';
    } else if (currentStatus === 'review') {
        if (btnApprove) btnApprove.style.display = 'inline-block';
        if (btnReject) btnReject.style.display = 'inline-block';
    } else if (currentStatus === 'approved' && btnReady) {
        btnReady.style.display = 'inline-block';
    }
}

function reset() {
    currentSkill = null;
    currentMarkdown = '';
    currentStatus = 'draft';
    workflowHistory = ['Created as draft'];
    
    document.getElementById('skillInput').value = '';
    document.getElementById('previewBox').style.display = 'none';
    document.getElementById('revisionSection').classList.remove('active');
    document.getElementById('thaiPanel').style.display = 'none';
    document.getElementById('resultMessage').textContent = '';
    document.getElementById('workflowSection').style.display = 'none';
    
    setStatus('', 'Ready');
}

// Initialize on load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Skill Creator initialized');
});
