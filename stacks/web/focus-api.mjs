#!/usr/bin/env node

/**
 * Focus Activity API
 * Simple API to serve focus activity data for the Focus Tracker UI
 */

import { readFileSync, existsSync } from 'fs';
import { createServer } from 'http';

const ACTIVITY_DB = '/home/tony/CascadeProjects/chaba/data/focus-activity.json';
const PORT = 3005;

/**
 * Load activity database
 */
function loadActivityDB() {
  if (!existsSync(ACTIVITY_DB)) {
    return {
      activities: [],
      focus_patterns: {},
      session_history: [],
      metadata: {
        created: new Date().toISOString(),
        last_updated: new Date().toISOString()
      }
    };
  }
  
  try {
    const content = readFileSync(ACTIVITY_DB, 'utf8');
    return JSON.parse(content);
  } catch (error) {
    console.error('Error loading activity database:', error.message);
    return null;
  }
}

/**
 * Get recent activities within time window
 */
function getRecentActivities(db, hours = 24) {
  const cutoff = new Date(Date.now() - hours * 60 * 60 * 1000);
  return db.activities.filter(a => new Date(a.timestamp) > cutoff);
}

/**
 * Get activity summary by focus area
 */
function getActivityByFocus(db, hours = 24) {
  const recentActivities = getRecentActivities(db, hours);
  const focusSummary = {};
  
  recentActivities.forEach(activity => {
    const focus = activity.focus_area || 'unassigned';
    if (!focusSummary[focus]) {
      focusSummary[focus] = {
        count: 0,
        total_impact: 0,
        last_activity: null,
        activity_types: {}
      };
    }
    
    focusSummary[focus].count++;
    focusSummary[focus].total_impact += activity.details.impact_score || 0;
    
    if (!focusSummary[focus].last_activity || new Date(activity.timestamp) > new Date(focusSummary[focus].last_activity)) {
      focusSummary[focus].last_activity = activity.timestamp;
    }
    
    const type = activity.activity_type;
    if (!focusSummary[focus].activity_types[type]) {
      focusSummary[focus].activity_types[type] = 0;
    }
    focusSummary[focus].activity_types[type]++;
  });
  
  return focusSummary;
}

/**
 * Get session history
 */
function getSessionHistory(db, limit = 10) {
  if (!db.session_history || db.session_history.length === 0) {
    return [];
  }
  
  return db.session_history.slice(-limit).reverse();
}

const server = createServer((req, res) => {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }
  
  const db = loadActivityDB();
  if (!db) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Failed to load activity database' }));
    return;
  }
  
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname;
  
  if (path === '/health' || path === '/api/focus/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', activities_count: db.activities.length }));
    return;
  }
  
  if (path === '/activities/recent' || path === '/api/focus/activities/recent') {
    const hours = parseInt(url.searchParams.get('hours') || '24', 10);
    const recent = getRecentActivities(db, hours);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(recent));
    return;
  }
  
  if (path === '/activities/summary' || path === '/api/focus/activities/summary') {
    const hours = parseInt(url.searchParams.get('hours') || '24', 10);
    const summary = getActivityByFocus(db, hours);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(summary));
    return;
  }
  
  if (path === '/sessions' || path === '/api/focus/sessions') {
    const limit = parseInt(url.searchParams.get('limit') || '10', 10);
    const sessions = getSessionHistory(db, limit);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(sessions));
    return;
  }
  
  if (path === '/stats' || path === '/api/focus/stats') {
    const stats = {
      total_activities: db.activities.length,
      focus_patterns: Object.keys(db.focus_patterns || {}).length,
      session_count: db.session_history?.length || 0,
      last_updated: db.metadata?.last_updated
    };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(stats));
    return;
  }
  
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Focus Activity API listening on port ${PORT}`);
});