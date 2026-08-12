#!/usr/bin/env node

/**
 * SSOT Validation Script
 * 
 * Validates all SSOT YAML files for syntax and structure using Python.
 */

import { readFileSync, readdirSync, existsSync, unlinkSync, writeFileSync, statSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';

const SSOT_DIR = '/home/tony/CascadeProjects/chaba/docs/ssot';

/**
 * Validate SSOT file using Python
 */
function validateSSOTFile(filePath) {
  const tempFile = `/tmp/ssot-validation-${Date.now()}.py`;
  
  const pythonScript = `
import yaml
import sys
import json

def validate_ssot(file_path):
    errors = []
    warnings = []
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Validate YAML syntax
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {'valid': False, 'errors': [f'YAML syntax error: {str(e)}'], 'warnings': []}
        
        if data is None:
            return {'valid': False, 'errors': ['Empty file'], 'warnings': []}
        
        # Check for required top-level fields (except config-type files)
        is_config_type = 'ssot.health' in file_path or 'ssot.gpu' in file_path or 'ssot.mcp' in file_path or 'ssot.automation' in file_path or 'ssot.containerization' in file_path
        
        if not is_config_type and 'title' not in data:
            errors.append('Missing required field: title')
        
        # Validate sections if they exist
        if 'sections' in data and isinstance(data['sections'], list):
            section_titles = set()
            
            for idx, section in enumerate(data['sections']):
                if 'title' not in section:
                    errors.append(f'Section {idx}: Missing required field: title')
                
                if 'icon' not in section:
                    warnings.append(f'Section {idx}: Missing recommended field: icon')
                
                if 'layout' not in section:
                    warnings.append(f'Section {idx}: Missing recommended field: layout')
                
                # Check for duplicate section titles
                if 'title' in section and section['title'] in section_titles:
                    errors.append(f'Duplicate section title: {section["title"]}')
                section_titles.add(section.get('title', ''))
                
                # Validate items if layout requires them
                if 'items' in section and isinstance(section['items'], list):
                    item_labels = set()
                    
                    for item_idx, item in enumerate(section['items']):
                        if 'label' not in item:
                            errors.append(f'Section {idx}, item {item_idx}: Missing required field: label')
                        
                        # Check for duplicate item labels
                        if 'label' in item and item['label'] in item_labels:
                            errors.append(f'Section {idx}: Duplicate item label: {item["label"]}')
                        item_labels.add(item.get('label', ''))
        
        # Validate ideas if they exist
        if 'ideas' in data and isinstance(data['ideas'], list):
            for idx, idea in enumerate(data['ideas']):
                if 'text' not in idea:
                    warnings.append(f'Idea {idx}: Missing recommended field: text')
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
        
    except Exception as e:
        return {'valid': False, 'errors': [f'Validation error: {str(e)}'], 'warnings': []}

if __name__ == '__main__':
    result = validate_ssot(r'${filePath}')
    print(json.dumps(result))
`;
  
  writeFileSync(tempFile, pythonScript, 'utf8');
  
  try {
    const result = execSync(`python3 ${tempFile}`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe']
    });
    
    unlinkSync(tempFile);
    return JSON.parse(result);
  } catch (error) {
    unlinkSync(tempFile);
    return { valid: false, errors: [`Python execution error: ${error.message}`], warnings: [] };
  }
}

/**
 * Process all SSOT files
 */
function processSSOTFiles() {
  if (!existsSync(SSOT_DIR)) {
    console.log('SSOT directory not found');
    return;
  }

  const files = [];
  
  // Recursively find all YAML files
  function findYAMLFiles(dir) {
    const items = readdirSync(dir);
    for (const item of items) {
      const fullPath = join(dir, item);
      const stat = statSync(fullPath);
      
      if (stat.isDirectory()) {
        findYAMLFiles(fullPath);
      } else if (item.endsWith('.yml') && !item.includes('template')) {
        files.push(fullPath);
      }
    }
  }
  
  findYAMLFiles(SSOT_DIR);
  
  console.log(`=== SSOT Validation Report ===\n`);
  console.log(`Found ${files.length} SSOT YAML files\n`);
  
  let totalErrors = 0;
  let totalWarnings = 0;
  let validFiles = 0;
  
  for (const file of files) {
    const relativePath = file.replace(SSOT_DIR + '/', '');
    console.log(`Validating: ${relativePath}`);
    
    const result = validateSSOTFile(file);
    
    if (result.errors.length > 0) {
      console.log(`  ❌ Errors:`);
      result.errors.forEach(error => {
        console.log(`    - ${error}`);
      });
      totalErrors += result.errors.length;
    }
    
    if (result.warnings.length > 0) {
      console.log(`  ⚠️  Warnings:`);
      result.warnings.forEach(warning => {
        console.log(`    - ${warning}`);
      });
      totalWarnings += result.warnings.length;
    }
    
    if (result.valid) {
      console.log(`  ✅ Valid`);
      validFiles++;
    }
    
    console.log();
  }
  
  console.log(`=== Summary ===`);
  console.log(`Total files checked: ${files.length}`);
  console.log(`Valid files: ${validFiles}`);
  console.log(`Total errors: ${totalErrors}`);
  console.log(`Total warnings: ${totalWarnings}`);
  
  if (totalErrors === 0) {
    console.log(`\n✅ All SSOT files are valid`);
  } else {
    console.log(`\n❌ ${files.length - validFiles} SSOT files have validation issues`);
  }
}

/**
 * Main execution
 */
function main() {
  processSSOTFiles();
}

main();