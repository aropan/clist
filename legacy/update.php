<?php
require_once "config.php";

/*
    foreach (glob("./cache/*") as $file)
    {
        print $file . "<br>\n";
        chmod($file, 0777);
    }
    chmod("./cache", 0777);
    return;
//*/
//parse_str(implode('&', array_slice($argv, 1)), $_GET);

$abbr_timezones = array();
$lines = explode("\n", trim(file_get_contents("timezones.list")));
foreach ($lines as $line) {
    list($abbr, $name, $timezone) = explode(",", $line);
    $abbr_timezones[$abbr] = array('name' => $name, 'timezone' => $timezone);
}
unset($lines);

$atimezone_rev = array();
foreach ($atimezone as $timezone => $value) {
    $dtimezone =
        timezone_offset_get(
            new DateTimeZone($timezone),
            new DateTime("now", new DateTimeZone("GMT"))
        );

    $dtime = ($dtimezone >= 0 ? '+' : '-') . sprintf("%02d:%02d", abs((int)$dtimezone) / 3600, abs((int)$dtimezone) % 3600 / 60);
    $atimezone_rev[$dtime] = $timezone;
}

$contests = array();
$enable = isset($_GET['enable']) ? $_GET['enable'] : 'TRUE';
if (isset($_GET['id'])) {
    $ids = array_map('intval', $_GET['id']);
    $resources = $db->select("clist_resource", "*", "enable = $enable and id in (" . implode(",", $ids) . ")");
} elseif (isset($_GET['host'])) {
    $likes = array_map(function ($s) use ($db) {
        return "host ~ '" . $db->escapeString($s) . "'";
    }, $_GET['host']);
    $resources = $db->select("clist_resource", "*", "enable = $enable and (" . implode(" or ", $likes) . ")");
} else {
    $resources = $db->select("clist_resource", "*", "enable = $enable");
}

echo "<i>" . date("r") . "</i><br><br>\n\n";

$resources_hosts = array();
$auto_remove_started = array();
foreach ($resources as $resource) {
    $start_parsing_time = microtime(true);
    $parse_url = empty($resource['parse_url']) ? $resource['url'] : $resource['parse_url'];
    $variables = array('${YEAR}' => date('Y'));
    $parse_url = strtr($parse_url, $variables);
    $resources_hosts[$resource['id']] = $resource['host'];


    echo "<b>{$resource['host']}</b>";
    $preCountContests = count($contests);
    if ($resource['path']) {
        $HOST_URL = $resource['url'];
        $URL = $parse_url;
        $HOST = $resource['host'];
        $RID = $resource['id'];
        $TIMEZONE = $resource['timezone'];
        $INFO = json_decode($resource['info'], true);
        $API_URL = $resource['api_url'];
        $PARSE_FULL_LIST = isset($_GET['parse_full_list']);
        $RESOURCE_URL = NULL;
        $RESOURCE_ICON_URL = NULL;

        include $resource['path'];

        if ($RESOURCE_URL && $resource["url"] != $RESOURCE_URL) {
            $resource["url"] = $RESOURCE_URL;
            $db->update("clist_resource", "url = '" . $db->escapeString($resource["url"]) . "'", "id = " . $resource["id"]);
        }

        if ($RESOURCE_ICON_URL && $resource["icon_url"] != $RESOURCE_ICON_URL) {
            $resource["icon_url"] = $RESOURCE_ICON_URL;
            $resource["icon_updated_at"] = NULL;
            $db->update("clist_resource", "icon_url = '" . $db->escapeString($resource["icon_url"]) . "', icon_updated_at = NULL", "id = " . $resource["id"]);
        }

        unset($HOST_URL);
        unset($URL);
        unset($HOST);
        unset($RID);
        unset($LANG);
        unset($TIMEZONE);
        unset($INFO);
        unset($RESOURCE_URL);
        unset($RESOURCE_ICON_URL);
    }
    if ($resource['regexp']) {
        $url = $parse_url;

        $page = curlexec($url);

        $page = str_replace("&nbsp;", " ", $page);
        $page = replace_russian_moths_to_number($page);

        preg_match_all($resource['regexp'], $page, $matches,  PREG_SET_ORDER);

        $timezone_offset = timezone_offset_get(new DateTimeZone($resource['timezone']), new DateTime("now"));

        $registration = NULL;
        foreach ($matches as $match) {
            foreach (
                array('date', 'date_start_time', 'date_end_time', 'start_date', 'end_date', 'start_time', 'end_time', 'duration', 'url', 'title', 'key')
                as $param
            ) $match[$param] = isset($match[$param]) ? trim(($match[$param])) : '';

            if ($match['date'] == "Сегодня") $match['date'] = date("Y-m-d", time() + $timezone_offset);
            if ($match['date'] == "Завтра") $match['date'] = date("Y-m-d", time() + 24 * 60 * 60 + $timezone_offset);

            if ($match['start_date'] && $match['start_time']) $match['start_time'] = $match['start_date'] . ' ' . $match['start_time'];
            if ($match['end_date'] && $match['end_time']) $match['end_time'] = $match['end_date'] . ' ' . $match['end_time'];

            $contest = array(
                'start_time' => $match['date'] && $match['date_start_time'] ? $match['date'] . ' ' . $match['date_start_time'] : $match['start_time'],
                'end_time' => $match['date'] && $match['date_end_time'] ? $match['date'] . ' ' . $match['date_end_time'] : $match['end_time'],
                'duration' => $match['duration'],
                'title' => $match['title'],
                'url' => $match['url'] ? $match['url'] : $resource['url']
            );
            $contest['start_time'] = str_replace('<br>', ' ', $contest['start_time']);
            $contest['end_time'] = str_replace('<br>', ' ', $contest['end_time']);

            if ($resource['host'] == 'stats.ioinformatics.org') {
                $no = $match['no'];
                $contest['title'] = $no . ending_ordinal($no) . ' International Olympiad in Informatics' . '. ' . $match['country'];
            }

            if ($resource['host'] == 'icfpcontest.org') {
                $contest['start_time'] = str_replace(' at ', ' ', $contest['start_time']);
                $contest['end_time'] = str_replace(' at ', ' ', $contest['end_time']);
            }

            if ($resource['host'] == 'stats.ioinformatics.org') {
                $contest['url'] = '/' . $contest['url'];
            }

            if ($resource['host'] == 'acm.hdu.edu.cn' && empty($contest['duration']))
                $contest['duration'] = '05:00';
            if ($resource['host'] == 'opencup.ru' && empty($contest['duration']))
                $contest['duration'] = '05:00';
            if ($resource['host'] == 'facebook.com/hackercup' && empty($contest['duration']) && empty($contest['end_time']))
                $contest['duration'] = '24:00';
            if ($resource['host'] == 'marathon24.com' && empty($contest['duration']))
                $contest['duration'] = '00:00';

            if (
                (int)(trim($contest['start_time']) == '') +
                (int)(trim($contest['end_time']) == '') +
                (int)(trim($contest['duration']) == '') > 1
            ) {
                continue;
            }

            if (!parse_url($contest['url'], PHP_URL_HOST)) {
                $url = empty($resource['parse_url']) ? $url : $resource['url'];
                if ($contest['url'][0] == '/')
                    $contest['url'] = parse_url($url, PHP_URL_SCHEME) . '://' . parse_url($url, PHP_URL_HOST) . $contest['url'];
                else
                    $contest['url'] = dirname($url . '.tmp') . '/' . $contest['url'];
            }

            $contest['title'] = preg_replace('#<br\s*\/?>#', '. ', $contest['title']);

            $contest['start_time'] = preg_replace("#\.(\d\d)\s#", '.' . (int)(date('Y', time()) / 100) . '\1 ', $contest['start_time']);
            $contest['end_time'] = preg_replace("#\.(\d\d)\s#", '.' . (int)(date('Y', time()) / 100) . '\1 ', $contest['end_time']);

            $contest['rid'] = $resource['id'];
            $contest['host'] = $resource['host'];
            $contest['timezone'] = $resource['timezone'];
            $contest['key'] = $match['key'] ? $match['key'] : ($match['url'] ? $contest['url'] : '');

            $contests[] = $contest;
        }
    }
    if ($resource['auto_remove_started'] == 't') {
        $auto_remove_started[$resource['id']] = true;
    }

    $elapsed_time = microtime(true) - $start_parsing_time;
    $elapsed_time_human_readable = sprintf("%0.3f", $elapsed_time);
    echo " (" . (count($contests) - $preCountContests) . ") [<i title=\"" . human_readable_seconds($elapsed_time) . "\">" . number_format($elapsed_time, 3) . "</i>]<br>\n";
}

$last_resource = "";
$updated_resources = array();
$skipped_resources = array();
foreach ($contests as $i => $contest) {
    foreach (array('start_time', 'end_time') as $k) {
        if (isset($contest[$k]) && !is_numeric($contest[$k]) && $contest[$k]) {
            if (!preg_match('/(?:[\-\+][0-9]+:[0-9]+|\s[A-Z]{3,}|Z|UTC\+[0-9]+)$/', $contest[$k]) and !empty($contest['timezone']) and strpos($contest[$k], $contest['timezone']) === false) {
                $contest[$k] .= " " . $contest['timezone'];
            }
            $contest[$k] = preg_replace('/\bUTC\b([+-][0-9]+)/i', '\1', $contest[$k]);
            $contest[$k] = preg_replace_callback(
                '/\s([A-Z]{3,})$/',
                function ($match) {
                    global $abbr_timezones;
                    global $atimezone_rev;
                    $t = $match[1];
                    if (!isset($abbr_timezones[$t])) {
                        return $match[0];
                    }
                    $t = $abbr_timezones[$t]['timezone'];
                    if (preg_match('/^UTC/', $t)) {
                        $t = substr($t, 3);
                    }
                    if (!strpos($t, ':')) {
                        $t .= ":00";
                    }
                    return " " . $atimezone_rev[$t];
                },
                $contest[$k]
            );
            $contest[$k] = strtotime($contest[$k]);
        }
    }

    if (isset($contest['duration']) && ($contest['duration'] || is_numeric($contest['duration']))) {
        $contest['duration'] = parse_duration($contest['duration']);
        if (isset($contest['start_time']) && empty($contest['end_time'])) $contest['end_time'] = $contest['start_time'] + $contest['duration'];
        if (empty($contest['start_time']) && isset($contest['end_time'])) $contest['start_time'] = $contest['end_time'] - $contest['duration'];
    }

    if (isset($contest['end_time']) && isset($contest['end_time_shift'])) $contest['end_time'] += strtotime(pop_item($contest, 'end_time_shift'), 0);
    if (isset($contest['start_time']) && isset($contest['start_time_shift'])) $contest['start_time'] += strtotime(pop_item($contest, 'start_time_shift'), 0);

    $contests[$i] = $contest;
}

$by_key = [];
foreach ($contests as $i => $contest) {
    if (!isset($contest['skip_update_key']) || !$contest['skip_update_key']) {
        switch ($contest['host']) {
            case 'dl.gsu.by':
                $contest['key'] = $contest['title'] . '. ' . date("d.m.Y", $contest['start_time']);
                break;
            case 'nerc.itmo.ru/trains':
                $contest['key'] = $contest['title'] . date(" d.m.Y", $contest['start_time']);
                break;
        }
    }

    foreach (
        array('start_time', 'end_time', 'duration', 'url', 'title', 'key', 'standings_url')
        as $param
    ) {
        if (isset($contest[$param])) $contests[$i][$param] = trim($contest[$param]);
    }
    if (isset($contest['key']) && $contest['key']) {
        $key = "${contest['key']} @ #${contest['rid']}";
        if (isset($by_key[$key])) {
            foreach ($contest as $k => $v) {
                $by_key[$key][$k] = $v;
            }
            unset($contests[$i]);
            $by_key[$key]['duplicate'] = true;
        } else {
            $by_key[$key] = &$contests[$i];
        }
    }
}
unset($by_key);

echo "<br><br>Total number of contests: " . count($contests) . "<br>";

function is_locked_contest($resource_id, $contest_key)
{
    global $db;
    $ctids = $db->select("clist_contest", "ctid::text AS ctid_txt", "resource_id = ${resource_id} AND key = '${contest_key}'");
    foreach ($ctids as $row) {
        $ctid = $row['ctid_txt'];
        $ctid_txt = substr($ctid, 1, -1);
        list($block, $offset) = explode(',', $ctid_txt);
        $locks = $db->getArray("
                SELECT * FROM pg_locks l
                JOIN pg_class c ON c.oid = l.relation
                WHERE c.relname = 'clist_contest' AND l.locktype = 'tuple' AND l.page = ${block} AND l.tuple = ${offset} AND l.granted = true
            ");
        if ($locks) {
            return true;
        }
    }
    return false;
}

foreach ($contests as $i => $contest) {
    //$timezone_offset = timezone_offset_get(new DateTimeZone($contest['timezone']), new DateTime("now"));
    //$contest['start_time'] -= $timezone_offset;
    //$contest['end_time'] -= $timezone_offset;

    $contest['title'] = trim(strip_tags(html_decode($contest['title'])));
    $contest['title'] = preg_replace_callback(
        "/(&#[0-9]+;)/",
        function ($m) {
            return mb_convert_encoding($m[1], "UTF-8", "HTML-ENTITIES");
        },
        $contest['title']
    );

    if (empty($contest['start_time']) || empty($contest['end_time'])) {
        continue;
    }

    if (time() + 365 * 24 * 60 * 60 < $contest['end_time']) {
        continue;
    }
    $get_skip_check_time = isset($_GET['skip_check_time']);
    $contest_skip_check_time = !empty($contest['skip_check_time']);
    if (!DEBUG && !$get_skip_check_time && !$contest_skip_check_time) {
        if ($contest['end_time'] + 31 * 24 * 60 * 60 < time()) continue;
    }
    if ($contest['end_time'] < $contest['start_time']) continue;

    if (!isset($contest['key']) || !$contest['key']) $contest['key'] = date("Y", $contest['start_time']) . " " . $contest['title'];

    if (empty($contest['duration_in_secs'])) {
        if (!empty($contest['duration'])) {
            $contest['duration_in_secs'] = $contest['duration'];
        } else {
            $contest['duration_in_secs'] = $contest['end_time'] - $contest['start_time'];
        }
    }

    $to_delete = ($contest['delete_after_end'] ?? false) && $contest['end_time'] < time();

    $contest['start_time'] = date('Y-m-d H:i:s', $contest['start_time']);
    $contest['end_time'] = date('Y-m-d H:i:s', $contest['end_time']);

    $fields = "resource_id";
    $values = $contest['rid'];
    $update = "resource_id = " . $contest['rid'];
    $contest_rid = $db->escapeString($contest['rid']);
    unset($contest['rid']);

    $duplicate = isset($contest['duplicate']) && $contest['duplicate'];

    $unchanged = isset($contest['unchanged']) ? $contest['unchanged'] : array();
    unset($contest['unchanged']);

    $info = false;
    $inherit_stage = false;
    if (isset($contest['info'])) {
        $inherit_stage = $contest['info']['_inherit_stage'] ?? false;
        $info = json_encode($contest['info'], JSON_HEX_APOS);
    }
    unset($contest['info']);

    unset($contest['duration']);
    unset($contest['timezone']);
    unset($contest['duplicate']);
    unset($contest['skip_check_time']);
    unset($contest['skip_update_key']);
    unset($contest['delete_after_end']);

    $contest = $db->escapeArray($contest);

    if (isset($contest['old_key'])) {
        $old_key = $contest['old_key'];
        $key = $contest['key'];
        $old_update = "$update and key = '${old_key}'";
        if (!$db->query("UPDATE clist_contest SET key = '$key' WHERE $old_update", true)) {
            $db->query("DELETE FROM clist_contest WHERE $old_update", true);
        }
    }
    unset($contest['old_key']);

    if (isset($contest['delete_key'])) {
        $delete_key = $contest['delete_key'];
        $delete_update = "$update and key = '${delete_key}'";
        $db->query("DELETE FROM clist_contest WHERE $delete_update", true);
    }
    unset($contest['delete_key']);

    $contest['is_auto_added'] = 1;
    $contest['auto_updated'] = date("Y-m-d H:i:s");

    foreach ($contest as $field => $value) {
        $fields .= ",$field";
        $values .= ",'$value'";
        if ($contest['host'] == 'stats.ioinformatics.org' && $field == 'duration_in_secs') {
            continue;
        }
        if ($unchanged && in_array($field, $unchanged)) {
            continue;
        }
        $update .= ",$field='$value'";
    }

    if ($info) {
        $fields .= ",info";
        $values .= ",'$info'::jsonb";
        $update .= ",info=clist_contest.info || '$info'::jsonb";
    }

    $slug = slugify($contest['title']);
    if ($slug) {
        $fields .= ",slug,title_path";
        $values .= ",'$slug','" . str_replace("-", ".", $slug) . "'";
    }

    $now = date("Y-m-d H:i:s", time());

    $to_update = !DEBUG && (!isset($_GET['title']) || preg_match($_GET['title'], $contest['title']));

    if (is_locked_contest($contest_rid, $contest['key'])) {
        $to_update = false;
    }

    if ($to_update) {
        if ($to_delete) {
            $db->query("DELETE FROM clist_contest WHERE resource_id = ${contest_rid} and key = '${contest['key']}'", true);
        } else {
            $db->query("INSERT INTO clist_contest ($fields) values ($values) ON CONFLICT (resource_id, key) DO UPDATE SET $update");
        }
    } else {
        $skipped_resources[$contest_rid][] = $contest['key'];
    }

    if (!$inherit_stage && $to_update) {
        $updated_resources[$contest_rid] = true;
    }

    $resource_host = $resources_hosts[$contest_rid];
    if ($last_resource != $resource_host) {
        echo "<br><b>$resource_host</b>:<br>\n";
        $last_resource = $resource_host;
    }

    $duration_human = human_readable_seconds($contest['duration_in_secs']);
    echo "\t<span style='padding-left: 50px'>" .
        ($duplicate ? "<i>duplicate</i> " : "") .
        ($to_update ? "" : "<i>skip</i> ") .
        ($to_delete ? "<i>delete</i> " : "") .
        "{$contest['title']} ({$contest['start_time']} | $duration_human) [{$contest['key']}]</span><br>\n";
}
if (count($updated_resources)) {
    $resources_filter = '';
    foreach (array_keys($updated_resources) as $resource_id) {
        if ($resources_filter) {
            $resources_filter .= ' OR ';
        }

        if (isset($auto_remove_started[$resource_id])) {
            $time_filter = "auto_updated < now() - interval '3 hours' AND now() < end_time";
        } else {
            $time_filter = "auto_updated < now() - interval '3 hours' AND now() < start_time";
        }
        $resource_filter = "resource_id = $resource_id AND $time_filter";

        $skipped_keys = $skipped_resources[$resource_id] ?? [];
        if ($skipped_keys) {
            $skipped_keys = "'" . implode("','", $skipped_keys) . "'";
            $resource_filter .= " AND key NOT IN ($skipped_keys)";
        }

        $resources_filter .= "($resource_filter)";
    }
    $query = "is_auto_added = true AND ($resources_filter)";
    $to_be_removed = $db->select("clist_contest", "*", $query);
    if ($to_be_removed) {
        $log_name = LOGREMOVEDDIR . date("Y-m-d_H-i-s", time());
        file_put_contents("$log_name-deleting.txt", print_r($to_be_removed, true));

        echo "<br><br><b><font color='red'>To be removed</font></b>:<br>\n";
        foreach ($to_be_removed as $contest) {
            echo "\t<span style='padding-left: 50px'>" .
                "{$contest['title']} [{$contest['key']}] <{$contest['url']}></span><br>\n";
        }
        if (!DEBUG) {
            $result = $db->delete("clist_contest", $query, array('ranking_stagecontest' => 'contest_id'));
            $deleted = array();
            while ($row = pg_fetch_array($result)) {
                $deleted[] = $row;
            }
            if (count($deleted)) {
                file_put_contents("$log_name-deleted.txt", print_r($deleted, true));
            }
        }
    }
}
logmsg();
