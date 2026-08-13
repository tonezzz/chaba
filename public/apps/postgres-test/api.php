<?php
/**
 * PostgreSQL Performance Test for chaba-h3
 * Tests database connection, query performance, and concurrent operations
 */

// Configuration - adjust these for your PostgreSQL setup
$db_config = [
    'host' => '172.17.0.1', // Docker bridge gateway (host.docker.internal alternative)
    'port' => '5432',
    'dbname' => 'chaba', // Main chaba database
    'user' => 'chaba', // Database user
    'password' => 'chabapass' // Default password from chaba infrastructure
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
    
    return [
        'avg_write_time_ms' => array_sum($times) / count($times),
        'min_write_time_ms' => min($times),
        'max_write_time_ms' => max($times),
        'writes_per_second' => 1000 / (array_sum($times) / count($times)),
        'iterations' => $iterations
    ];
}

/**
 * Test 4: Read Performance
 */
function testReadPerformance($conn) {
    // Create test table with data
    pg_query($conn, "DROP TABLE IF EXISTS read_test");
    pg_query($conn, "CREATE TABLE read_test (id SERIAL, value INTEGER, data TEXT)");
    
    // Insert 1000 rows
    for ($i = 0; $i < 1000; $i++) {
        pg_query($conn, "INSERT INTO read_test (value, data) VALUES ($i, 'data $i')");
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
        return ['error' => 'Read operations failed'];
    }
    
    return [
        'avg_read_time_ms' => array_sum($times) / count($times),
        'min_read_time_ms' => min($times),
        'max_read_time_ms' => max($times),
        'reads_per_second' => 1000 / (array_sum($times) / count($times)),
        'iterations' => $iterations
    ];
}

/**
 * Test 5: Concurrent Operations
 */
function testConcurrentOperations($conn) {
    // Create test table
    pg_query($conn, "DROP TABLE IF EXISTS concurrent_test");
    pg_query($conn, "CREATE TABLE concurrent_test (id SERIAL, operation_type TEXT, data TEXT, created_at TIMESTAMP DEFAULT NOW())");
    
    $times = [];
    $operations = 50;
    
    for ($i = 0; $i < $operations; $i++) {
        $start = microtime(true);
        
        // Mix of read and write operations
        if ($i % 2 == 0) {
            pg_query($conn, "INSERT INTO concurrent_test (operation_type, data) VALUES ('write', 'data $i')");
        } else {
            pg_query($conn, "SELECT * FROM concurrent_test LIMIT 10");
        }
        
        $times[] = (microtime(true) - $start) * 1000; // Convert to ms
    }
    
    if (empty($times)) {
        return ['error' => 'Concurrent operations failed'];
    }
    
    $avg_time = array_sum($times) / count($times);
    
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

// Main execution - auto-run for GET requests or CLI
$run_tests = isset($_POST['run_tests']) || isset($_GET['run_tests']) || (isset($_SERVER['REQUEST_METHOD']) && $_SERVER['REQUEST_METHOD'] === 'GET') || (php_sapi_name() === 'cli');

// Output HTML wrapper
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
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 chaba-h3 PostgreSQL Performance Test</h1>
<?php

if ($run_tests) {
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
        
        // Reconnect for remaining tests
        $conn = pg_connect(
            "host={$db_config['host']} " .
            "port={$db_config['port']} " .
            "dbname={$db_config['dbname']} " .
            "user={$db_config['user']} " .
            "password={$db_config['password']}"
        );
        
        if (!$conn) {
            throw new Exception("Failed to reconnect to PostgreSQL");
        }
        
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
            echo '<div class="metric"><span class="metric-label">Queries Per Second:</span><span class="metric-value">' . number_format($results['simple_query']['queries_per_second'], 2) . '</span></div>';
            echo '<div class="metric"><span class="metric-label">Iterations:</span><span class="metric-value">' . $results['simple_query']['iterations'] . '</span></div>';
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
            echo '<div class="metric"><span class="metric-label">Writes Per Second:</span><span class="metric-value">' . number_format($results['write_performance']['writes_per_second'], 2) . '</span></div>';
            echo '<div class="metric"><span class="metric-label">Iterations:</span><span class="metric-value">' . $results['write_performance']['iterations'] . '</span></div>';
            echo '</div>';
        }
        echo '</div>';
        
        echo '<div class="test-section">';
        echo '<h2>Test 4: Read Performance</h2>';
        $results['read_performance'] = testReadPerformance($conn);
        if (isset($results['read_performance']['error'])) {
            echo '<div class="error">❌ ' . $results['read_performance']['error'] . '</div>';
        } else {
            echo '<div class="result">';
            echo '<div class="metric"><span class="metric-label">Average Read Time:</span><span class="metric-value">' . number_format($results['read_performance']['avg_read_time_ms'], 3) . ' ms</span></div>';
            echo '<div class="metric"><span class="metric-label">Min Read Time:</span><span class="metric-value">' . number_format($results['read_performance']['min_read_time_ms'], 3) . ' ms</span></div>';
            echo '<div class="metric"><span class="metric-label">Max Read Time:</span><span class="metric-value">' . number_format($results['read_performance']['max_read_time_ms'], 3) . ' ms</span></div>';
            echo '<div class="metric"><span class="metric-label">Reads Per Second:</span><span class="metric-value">' . number_format($results['read_performance']['reads_per_second'], 2) . '</span></div>';
            echo '<div class="metric"><span class="metric-label">Iterations:</span><span class="metric-value">' . $results['read_performance']['iterations'] . '</span></div>';
            echo '</div>';
        }
        echo '</div>';
        
        echo '<div class="test-section">';
        echo '<h2>Test 5: Concurrent Operations</h2>';
        $results['concurrent_operations'] = testConcurrentOperations($conn);
        if (isset($results['concurrent_operations']['error'])) {
            echo '<div class="error">❌ ' . $results['concurrent_operations']['error'] . '</div>';
        } else {
            echo '<div class="result">';
            echo '<div class="metric"><span class="metric-label">Average Operation Time:</span><span class="metric-value">' . number_format($results['concurrent_operations']['avg_operation_time_ms'], 3) . ' ms</span></div>';
            echo '<div class="metric"><span class="metric-label">Min Operation Time:</span><span class="metric-value">' . number_format($results['concurrent_operations']['min_operation_time_ms'], 3) . ' ms</span></div>';
            echo '<div class="metric"><span class="metric-label">Max Operation Time:</span><span class="metric-value">' . number_format($results['concurrent_operations']['max_operation_time_ms'], 3) . ' ms</span></div>';
            echo '<div class="metric"><span class="metric-label">Operations Per Second:</span><span class="metric-value">' . number_format($results['concurrent_operations']['operations_per_second'], 2) . '</span></div>';
            echo '<div class="metric"><span class="metric-label">Total Operations:</span><span class="metric-value">' . $results['concurrent_operations']['total_operations'] . '</span></div>';
            echo '</div>';
        }
        echo '</div>';
        
        echo '<div class="test-section">';
        echo '<h2>PostgreSQL Information</h2>';
        echo '<div class="result">';
        echo '<div class="metric"><span class="metric-label">Version:</span><span class="metric-value">' . htmlspecialchars($results['postgres_info']['version']) . '</span></div>';
        echo '<div class="metric"><span class="metric-label">Database Size:</span><span class="metric-value">' . htmlspecialchars($results['database_size']['size']) . '</span></div>';
        echo '</div>';
        echo '</div>';
        
        pg_close($conn);
        
    } catch (Exception $e) {
        echo '<div class="error">❌ Database Error: ' . htmlspecialchars($e->getMessage()) . '</div>';
    }
} else {
    echo '<div class="error">❌ Please submit the form to run tests</div>';
}
?>
    </div>
</body>
</html>