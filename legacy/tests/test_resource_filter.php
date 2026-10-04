<?php

// Offline request-filter regression tests: php tests/test_resource_filter.php
require_once __DIR__ . '/harness.php';
require_once dirname(__DIR__) . '/resource_filter.php';

$tests = 0;
function resource_filter_assert($condition, $message)
{
    global $tests;
    $tests++;
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

foreach ([null, false, '1', [], [[1]], [new stdClass()], [true, 1.5], ['1) OR TRUE --'], ['2147483648']] as $values) {
    resource_filter_assert(normalize_resource_ids($values) === [-1], 'invalid resource IDs must be discarded');
}
resource_filter_assert(normalize_resource_ids(['1', 2, '1', '-1', '0']) === [1, 2], 'valid resource IDs must be preserved and deduplicated');
resource_filter_assert(normalize_resource_ids(['1) OR TRUE --', '2']) === [2], 'mixed input must retain only valid resource IDs');
resource_filter_assert(resource_ids_from_cookie(serialize(['1', '2'])) === [1, 2], 'existing cookies must remain readable');
foreach (['', 'malformed', serialize(false), serialize('1'), serialize(['1) OR TRUE --']), ['array-cookie']] as $cookie) {
    resource_filter_assert(resource_ids_from_cookie($cookie) === [-1], 'invalid cookies must fall back to all resources');
}

class ResourceFilterCookieObject
{
    public function __wakeup(): void
    {
        throw new RuntimeException('cookie objects must never be instantiated');
    }
}
resource_filter_assert(resource_ids_from_cookie(serialize([new ResourceFilterCookieObject()])) === [-1], 'cookie objects must be rejected');

// Run the actual entry point with fake configuration in a separate directory: no DB or network.
$sandbox = sys_get_temp_dir() . '/clist-resource-filter-' . bin2hex(random_bytes(8));
mkdir($sandbox);
try {
    copy(dirname(__DIR__) . '/index.php', $sandbox . '/index.php');
    copy(dirname(__DIR__) . '/resource_filter.php', $sandbox . '/resource_filter.php');
    file_put_contents($sandbox . '/config.php', <<<'PHP'
<?php
$atimezone = ['Europe/Kaliningrad' => ['value' => 0]];
$adurationlimit = ['no limit' => PHP_INT_MAX];
$db = new class {
    public array $queries = [];
    public function getArray($sql, $params = null): array
    {
        $this->queries[] = [$sql, $params];
        if (str_starts_with($sql, 'SELECT id FROM clist_resource WHERE host')) {
            return [['id' => '3']];
        }
        return [];
    }
};
$smarty = new class {
    public int $caching = 0;
    public function assign($name, $value): void {}
    public function display($name): void {}
};
PHP);
    file_put_contents($sandbox . '/run.php', <<<'PHP'
<?php
chdir(__DIR__);
[$_GET, $_POST, $_COOKIE] = json_decode($argv[1], true);
$_SERVER['DOCUMENT_ROOT'] = __DIR__;
require 'index.php';
echo json_encode($db->queries);
PHP);

    $cases = [
        [['arid' => ['1', '2']], [], [], '{1,2}'],
        [['arid' => ['1) OR TRUE --']], [], [], '{-1}'],
        [[], ['arid' => ['1) OR TRUE --', '2']], [], '{2}'],
        [[], [], ['arid' => serialize(['1) OR TRUE --'])], '{-1}'],
        [[], [], ['arid' => serialize(['1', '2'])], '{1,2}'],
        [['arid' => '1) OR TRUE --'], [], [], '{-1}'],
        [['arid' => [['1) OR TRUE --']]], [], [], '{-1}'],
        [['byhosts' => "example.com,') OR TRUE --"], [], [], '{3}'],
        [[], ['action' => 'resources', 'arid' => ['1) OR TRUE --', '2']], [], '{2}'],
        [[], ['action' => 'resources'], ['arid' => serialize(['1'])], '{-1}'],
    ];
    foreach (['list', 'rss', 'calendar', 'latestadded'] as $view) {
        foreach ($cases as [$get, $post, $cookies, $expected_ids]) {
            $get['view'] = $view === 'latestadded' ? 'list' : $view;
            if ($view === 'latestadded') {
                $get['mode'] = $view;
            }
            $code = fixture_exec_child([PHP_BINARY, $sandbox . '/run.php', json_encode([$get, $post, $cookies])], $stdout, $stderr);
            resource_filter_assert($code === 0 && $stderr === '', "entry point must handle $view requests without errors: $stderr");
            $queries = json_decode($stdout, true, 512, JSON_THROW_ON_ERROR);
            $filtered_queries = 0;
            foreach ($queries as [$sql, $params]) {
                resource_filter_assert(!str_contains($sql, 'OR TRUE'), 'request input must never enter SQL syntax');
                if (str_starts_with($sql, 'SELECT id FROM clist_resource WHERE host')) {
                    resource_filter_assert($params === explode(',', $get['byhosts']), 'host names must be bound without altering their values');
                }
                if (!str_contains($sql, 'ANY(')) {
                    continue;
                }
                $filtered_queries++;
                resource_filter_assert($params[0] === $expected_ids, 'resource IDs must be bound as a PostgreSQL array');
                preg_match_all('/\$\d+/', $sql, $placeholders);
                resource_filter_assert(count(array_unique($placeholders[0])) === count($params), 'every SQL parameter must have a placeholder');
            }
            resource_filter_assert($filtered_queries >= 2, 'both resources and contests/calendars must use bound resource IDs');
        }
    }

    // Disable PHP extensions and replace pg_* functions to verify the DB wrapper without connecting.
    copy(dirname(__DIR__) . '/db.class.php', $sandbox . '/db.class.php');
    file_put_contents($sandbox . '/helper.php', '<?php');
    file_put_contents($sandbox . '/test_db.php', <<<'PHP'
<?php
chdir(__DIR__);
define('SKIP_DB_CONNECT', true);
$calls = [];
function pg_query($connection, $sql)
{
    $GLOBALS['calls'][] = ['query', $sql];
    return true;
}
function pg_query_params($connection, $sql, $params)
{
    $GLOBALS['calls'][] = ['params', $sql, $params];
    return true;
}
function pg_fetch_assoc($result)
{
    return false;
}
require 'db.class.php';
$db = new class extends db {
    public function __construct() {}
};
$db->getArray('SELECT 1');
$db->getArray('SELECT $1', ['1) OR TRUE --']);
$db->getArray('SELECT 1', []);
echo json_encode($calls);
PHP);
    $code = fixture_exec_child([PHP_BINARY, '-n', $sandbox . '/test_db.php'], $stdout, $stderr);
    resource_filter_assert($code === 0 && $stderr === '', "DB wrapper must run without external services: $stderr");
    resource_filter_assert(json_decode($stdout, true) === [
        ['query', 'SELECT 1'],
        ['params', 'SELECT $1', ['1) OR TRUE --']],
        ['params', 'SELECT 1', []],
    ], 'DB wrapper must preserve old callers and route bound parameters through pg_query_params');
} finally {
    fixture_rmdir_recursive($sandbox);
}

echo "all $tests resource filter assertion(s) passed\n";
