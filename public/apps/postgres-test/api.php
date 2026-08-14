<?php
/**
 * PostgreSQL Performance Test for chaba-h3
 * Tests database connection, query performance, and concurrent operations
 */

// Configuration - adjust these for your chaba PostgreSQL setup
$db_config = [
    'host' => 'localhost',
    'port' => '5432',
    'dbname' => 'chaba', // Main chaba database
    'user' => 'tony', // Database user
    'password' => 'Love2521**' // PostgreSQL password
];

// Test results storage
$results = [];

/**
 * Test 1: Connection Latency
 */
function testConnectionLatency($config) {
    $times = [];
    $iterations = 10;
    
    for ($i = 0; $i < $iterations; $i++) {
        $start = microtime(true);
        try {
            $conn = pg_connect(
                "host={$config['host']} " .
                "port={$config['port']} " .
                "dbname={$config['dbname']} " .
                "user={$config['user']} " .
                "password={$config['password']}"
            );
            if ($conn) {
                pg_close($conn);
                $times[] = (microtime(true) - $start) * 1000; // Convert to ms
            }
        } catch (Exception $e) {
            return ['error' => $e->getMessage()];
        }
    }
    
    if (empty($times)) {
        return ['error' => 'Could not establish any connections'];
    }
    
    return [
        'avg_latency_ms' => array_sum($times) / count($times),
        'min_latency_ms' => min($times),
        'max_latency_ms' => max($times),
        'iterations' => $iterations
    ];
}

/**
 * Test 2: Simple Query Performance
 */
function testSimpleQuery($conn) {
    $times = [];
    $iterations = 100;
    
    for ($i = 0; $i < $iterations; $i++) {
        $start = microtime(true);
        $result = pg_query($conn, "SELECT 1");
        if ($result) {
            pg_free_result($result);
            $times[] = (microtime(true) - $start) * 1000; // Convert to ms
        }
    }
    
    if (empty($times)) {
        return ['error' => 'Query execution failed'];
    }
    
    return [
        'avg_query_time_ms' => array_sum($times) / count($times),
        'min_query_time_ms' => min($times),
        'max_query_time_ms' => max($times),
        'queries_per_second' => 1000 / (array_sum($times) / count($times)),
        'iterations' => $iterations
    ];
}

/**
 * Test 3: Write Performance
 */
function testWritePerformance($conn) {
    // Create test table if not exists
    pg_query($conn, "DROP TABLE IF EXISTS performance_test");
    pg_query($conn, "CREATE TABLE performance_test (id SERIAL, data TEXT, created_at TIMESTAMP DEFAULT NOW())");
    
    $times = [];
    $iterations = 50;
    
    for ($i = 0; $i < $iterations; $i++) {
        $start = microtime(true);
        $result = pg_query($conn, "INSERT INTO performance_test (data) VALUES ('test data $i')");
        if ($result) {
            $times[] = (microtime(true) - $start) * 1000; // Convert to ms
        }
    }
    
    if (empty($times)) {
        return ['error' => 'Write operations failed'];
    }
    
    $avg_write_time = array_sum($times) / count($times);
    
    // Cleanup
    pg_query($conn, "DROP TABLE performance_test");
    
    return [
        'avg_write_time_ms' => $avg_write_time,
        'min_write_time_ms' => min($times),
        'max_write_time_ms' => max($times),
        'writes_per_second' => 1000 / $avg_write_time,
        'iterations' => $iterations
    ];
}

/**
 * Test 4: Read Performance
 */
function testReadPerformance($conn) {
    // Create test table with sample data
    pg_query($conn, "DROP TABLE IF EXISTS read_test");
    pg_query($conn, "CREATE TABLE read_test (id SERIAL, data TEXT, value INTEGER)");
    
    // Insert sample data
    for ($i = 0; $i < 1000; $i++) {
        pg_query($conn, "INSERT INTO read_test (data, value) VALUES ('data $i', $i)");
    }
    
    $times = [];
    $iterations = 100;
    
    for ($i = 0; $i < $iterations; $i++) {
        $start = microtime(true);
        $result = pg_query($conn, "SELECT * FROM read_test WHERE value = " . rand(0, 999));
        if ($result) {
            pg_free_result($result);
            $times[] = (microtime(true) - $start) * 1000; // Convert to ms
        }
    }
    
    if (empty($times)) {
        pg_query($conn, "DROP TABLE read_test");
        return ['error' => 'Read operations failed'];
    }
    
    $avg_read_time = array_sum($times) / count($times);
    
    // Cleanup
    pg_query($conn, "DROP TABLE read_test");
    
    return [
        'avg_read_time_ms' => $avg_read_time,
        'min_read_time_ms' => min($times),
        'max_read_time_ms' => max($times),
        'reads_per_second' => 1000 / $avg_read_time,
        'iterations' => $iterations
    ];
}

/**
 * Test 5: Concurrent Operations Simulation
 */
function testConcurrentOperations($conn) {
    // Create test table
    pg_query($conn, "DROP TABLE IF EXISTS concurrent_test");
    pg_query($conn, "CREATE TABLE concurrent_test (id SERIAL, operation_type TEXT, timestamp TIMESTAMP DEFAULT NOW())");
    
    $operations = 50;
    $times = [];
    
    for ($i = 0; $i < $operations; $i++) {
        $start = microtime(true);
        
        // Mix of reads and writes
        if ($i % 2 == 0) {
            pg_query($conn, "INSERT INTO concurrent_test (operation_type) VALUES ('write')");
        } else {
            pg_query($conn, "SELECT COUNT(*) FROM concurrent_test");
        }
        
        $times[] = (microtime(true) - $start) * 1000;
    }
    
    if (empty($times)) {
        pg_query($conn, "DROP TABLE concurrent_test");
        return ['error' => 'Concurrent operations failed'];
    }
    
    $avg_time = array_sum($times) / count($times);
    
    // Cleanup
    pg_query($conn, "DROP TABLE concurrent_test");
    
    return [
        'avg_operation_time_ms' => $avg_time,
        'min_operation_time_ms' => min($times),
        'max_operation_time_ms' => max($times),
        'operations_per_second' => 1000 / $avg_time,
        'total_operations' => $operations
    ];
}

/**
 * Get PostgreSQL Version Information
 */
function getPostgresInfo($conn) {
    $result = pg_query($conn, "SELECT version()");
    if ($result) {
        $row = pg_fetch_row($result);
        pg_free_result($result);
        return ['version' => $row[0]];
    }
    return ['error' => 'Could not get version info'];
}

/**
 * Get Database Size
 */
function getDatabaseSize($conn) {
    $result = pg_query($conn, "SELECT pg_size_pretty(pg_database_size(current_database()))");
    if ($result) {
        $row = pg_fetch_row($result);
        pg_free_result($result);
        return ['size' => $row[0]];
    }
    return ['error' => 'Could not get database size'];
}

// Main execution
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>chaba-h3 PostgreSQL Performance Test</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
        }
        .test-section {
            margin: 20px 0;
            padding: 20px;
            border: 1px solid #ddd;
            border-radius: 5px;
            background: #f9f9f9;
        }
        .test-section h2 {
            color: #007bff;
            margin-top: 0;
        }
        .result {
            background: white;
            padding: 15px;
            border-radius: 4px;
            margin: 10px 0;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }
        .metric:last-child {
            border-bottom: none;
        }
        .metric-label {
            font-weight: 600;
            color: #555;
        }
        .metric-value {
            color: #007bff;
            font-family: 'Courier New', monospace;
        }
        .error {
            color: #dc3545;
            background: #f8d7da;
            padding: 10px;
            border-radius: 4px;
            border: 1px solid #f5c6cb;
        }
        .success {
            color: #155724;
            background: #d4edda;
            padding: 10px;
            border-radius: 4px;
            border: 1px solid #c3e6cb;
        }
        .config-warning {
            background: #fff3cd;
            color: #856404;
            padding: 15px;
            border-radius: 4px;
            border: 1px solid #ffeeba;
            margin: 20px 0;
        }
        .run-button {
            background: #007bff;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            margin: 10px 0;
        }
        .run-button:hover {
            background: #0056b3;
        }
        .comparison {
            background: #e7f3ff;
            padding: 15px;
            border-radius: 4px;
            border: 1px solid #b8daff;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 chaba-h3 PostgreSQL Performance Test</h1>
        
        <div class="config-warning">
            <strong>⚠️ Configuration Required:</strong> 
            Please update the database configuration in this script with your actual 
            PostgreSQL credentials before running the tests.
        </div>

        <form method="post">
            <button type="submit" name="run_tests" class="run-button">🧪 Run Performance Tests</button>
        </form>

        <?php if (isset($_POST['run_tests'])): ?>
            <?php
            // Update configuration from form if provided
            if (!empty($_POST['db_host'])) $db_config['host'] = $_POST['db_host'];
            if (!empty($_POST['db_port'])) $db_config['port'] = $_POST['db_port'];
            if (!empty($_POST['db_name'])) $db_config['dbname'] = $_POST['db_name'];
            if (!empty($_POST['db_user'])) $db_config['user'] = $_POST['db_user'];
            if (!empty($_POST['db_password'])) $db_config['password'] = $_POST['db_password'];
            
            // Connect to database
            try {
                $conn = pg_connect(
                    "host={$db_config['host']} " .
                    "port={$db_config['port']} " .
                    "dbname={$db_config['dbname']} " .
                    "user={$db_config['user']} " .
                    "password={$db_config['password']}"
                );
                
                if (!$conn) {
                    throw new Exception("Failed to connect to PostgreSQL");
                }
                
                echo '<div class="success">✅ Successfully connected to PostgreSQL</div>';
                
                // Get PostgreSQL info
                $results['postgres_info'] = getPostgresInfo($conn);
                $results['database_size'] = getDatabaseSize($conn);
                
                // Run performance tests
                echo '<div class="test-section">';
                echo '<h2>Test 1: Connection Latency</h2>';
                $results['connection_latency'] = testConnectionLatency($db_config);
                if (isset($results['connection_latency']['error'])) {
                    echo '<div class="error">❌ ' . $results['connection_latency']['error'] . '</div>';
                } else {
                    echo '<div class="result">';
                    echo '<div class="metric"><span class="metric-label">Average Latency:</span><span class="metric-value">' . number_format($results['connection_latency']['avg_latency_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Min Latency:</span><span class="metric-value">' . number_format($results['connection_latency']['min_latency_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Max Latency:</span><span class="metric-value">' . number_format($results['connection_latency']['max_latency_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Iterations:</span><span class="metric-value">' . $results['connection_latency']['iterations'] . '</span></div>';
                    echo '</div>';
                }
                echo '</div>';
                
                echo '<div class="test-section">';
                echo '<h2>Test 2: Simple Query Performance</h2>';
                $results['simple_query'] = testSimpleQuery($conn);
                if (isset($results['simple_query']['error'])) {
                    echo '<div class="error">❌ ' . $results['simple_query']['error'] . '</div>';
                } else {
                    echo '<div class="result">';
                    echo '<div class="metric"><span class="metric-label">Average Query Time:</span><span class="metric-value">' . number_format($results['simple_query']['avg_query_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Min Query Time:</span><span class="metric-value">' . number_format($results['simple_query']['min_query_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Max Query Time:</span><span class="metric-value">' . number_format($results['simple_query']['max_query_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Queries/Second:</span><span class="metric-value">' . number_format($results['simple_query']['queries_per_second'], 1) . '</span></div>';
                    echo '</div>';
                }
                echo '</div>';
                
                echo '<div class="test-section">';
                echo '<h2>Test 3: Write Performance</h2>';
                $results['write_performance'] = testWritePerformance($conn);
                if (isset($results['write_performance']['error'])) {
                    echo '<div class="error">❌ ' . $results['write_performance']['error'] . '</div>';
                } else {
                    echo '<div class="result">';
                    echo '<div class="metric"><span class="metric-label">Average Write Time:</span><span class="metric-value">' . number_format($results['write_performance']['avg_write_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Min Write Time:</span><span class="metric-value">' . number_format($results['write_performance']['min_write_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Max Write Time:</span><span class="metric-value">' . number_format($results['write_performance']['max_write_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Writes/Second:</span><span class="metric-value">' . number_format($results['write_performance']['writes_per_second'], 1) . '</span></div>';
                    echo '</div>';
                }
                echo '</div>';
                
                echo '<div class="test-section">';
                echo '<h2>Test 4: Read Performance (1000 rows)</h2>';
                $results['read_performance'] = testReadPerformance($conn);
                if (isset($results['read_performance']['error'])) {
                    echo '<div class="error">❌ ' . $results['read_performance']['error'] . '</div>';
                } else {
                    echo '<div class="result">';
                    echo '<div class="metric"><span class="metric-label">Average Read Time:</span><span class="metric-value">' . number_format($results['read_performance']['avg_read_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Min Read Time:</span><span class="metric-value">' . number_format($results['read_performance']['min_read_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Max Read Time:</span><span class="metric-value">' . number_format($results['read_performance']['max_read_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Reads/Second:</span><span class="metric-value">' . number_format($results['read_performance']['reads_per_second'], 1) . '</span></div>';
                    echo '</div>';
                }
                echo '</div>';
                
                echo '<div class="test-section">';
                echo '<h2>Test 5: Concurrent Operations (Mixed Read/Write)</h2>';
                $results['concurrent_ops'] = testConcurrentOperations($conn);
                if (isset($results['concurrent_ops']['error'])) {
                    echo '<div class="error">❌ ' . $results['concurrent_ops']['error'] . '</div>';
                } else {
                    echo '<div class="result">';
                    echo '<div class="metric"><span class="metric-label">Average Operation Time:</span><span class="metric-value">' . number_format($results['concurrent_ops']['avg_operation_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Min Operation Time:</span><span class="metric-value">' . number_format($results['concurrent_ops']['min_operation_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Max Operation Time:</span><span class="metric-value">' . number_format($results['concurrent_ops']['max_operation_time_ms'], 3) . ' ms</span></div>';
                    echo '<div class="metric"><span class="metric-label">Operations/Second:</span><span class="metric-value">' . number_format($results['concurrent_ops']['operations_per_second'], 1) . '</span></div>';
                    echo '</div>';
                }
                echo '</div>';
                
                // Database info
                echo '<div class="test-section">';
                echo '<h2>Database Information</h2>';
                echo '<div class="result">';
                if (isset($results['postgres_info']['version'])) {
                    echo '<div class="metric"><span class="metric-label">PostgreSQL Version:</span><span class="metric-value">' . htmlspecialchars($results['postgres_info']['version']) . '</span></div>';
                }
                if (isset($results['database_size']['size'])) {
                    echo '<div class="metric"><span class="metric-label">Database Size:</span><span class="metric-value">' . htmlspecialchars($results['database_size']['size']) . '</span></div>';
                }
                echo '</div>';
                echo '</div>';
                
                pg_close($conn);
                
            } catch (Exception $e) {
                echo '<div class="error">❌ Error: ' . htmlspecialchars($e->getMessage()) . '</div>';
            }
            ?>
            
            <div class="comparison">
                <h3>📊 Performance Comparison Notes</h3>
                <p><strong>Expected Local PostgreSQL Performance:</strong></p>
                <ul>
                    <li>Simple Query: ~0.4ms</li>
                    <li>Write Operations: ~0.3ms</li>
                    <li>Read Operations: ~1.2ms (100 rows)</li>
                    <li>Concurrent Operations: ~3ms (100 ops)</li>
                </ul>
                <p><strong>Shared Hosting Considerations:</strong></p>
                <ul>
                    <li>Performance may vary based on server load</li>
                    <li>Resource contention with other hosted sites</li>
                    <li>Network latency even for localhost connections</li>
                    <li>Connection pool limitations</li>
                </ul>
            </div>
            
            <div class="test-section">
                <h2>🔧 Configuration Form</h2>
                <form method="post">
                    <div class="metric">
                        <label class="metric-label">Host:</label>
                        <input type="text" name="db_host" value="<?php echo htmlspecialchars($db_config['host']); ?>">
                    </div>
                    <div class="metric">
                        <label class="metric-label">Port:</label>
                        <input type="text" name="db_port" value="<?php echo htmlspecialchars($db_config['port']); ?>">
                    </div>
                    <div class="metric">
                        <label class="metric-label">Database Name:</label>
                        <input type="text" name="db_name" value="<?php echo htmlspecialchars($db_config['dbname']); ?>">
                    </div>
                    <div class="metric">
                        <label class="metric-label">Username:</label>
                        <input type="text" name="db_user" value="<?php echo htmlspecialchars($db_config['user']); ?>">
                    </div>
                    <div class="metric">
                        <label class="metric-label">Password:</label>
                        <input type="password" name="db_password" value="">
                    </div>
                    <button type="submit" name="run_tests" class="run-button">🧪 Run Tests with New Configuration</button>
                </form>
            </div>
            
        <?php endif; ?>
        
        <div class="test-section">
            <h2>📋 Test Descriptions</h2>
            <div class="result">
                <p><strong>Test 1 - Connection Latency:</strong> Measures the time to establish 10 database connections and calculates average, min, and max latency.</p>
                <p><strong>Test 2 - Simple Query:</strong> Executes 100 simple SELECT 1 queries to measure basic query performance.</p>
                <p><strong>Test 3 - Write Performance:</strong> Performs 50 INSERT operations to measure write performance.</p>
                <p><strong>Test 4 - Read Performance:</strong> Creates a table with 1000 rows and performs 100 SELECT queries with random values.</p>
                <p><strong>Test 5 - Concurrent Operations:</strong> Simulates 50 mixed read/write operations to test concurrent performance.</p>
            </div>
        </div>
    </div>
</body>
</html>