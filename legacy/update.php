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

        $dtime = ($dtimezone >= 0? '+' : '-') . sprintf("%02d:%02d", abs((int)$dtimezone) / 3600, abs((int)$dtimezone) % 3600 / 60);
        $atimezone_rev[$dtime] = $timezone;
    }

    $contests = array();
    $enable = isset($_GET['enable'])? $_GET['enable'] : 'TRUE';
    if (isset($_GET['id'])) {
        $ids = array_map('intval', $_GET['id']);
        $resources = $db->select("clist_resource", "*", "enable = $enable and id in (" . implode(",", $ids) . ")");
    } elseif (isset($_GET['host'])) {
        $likes = array_map(function ($s) use ($db) { return "host LIKE '%" . $db->escapeString($s) . "%'"; }, $_GET['host']);
        $resources = $db->select("clist_resource", "*", "enable = $enable and (" . implode(" or ", $likes) . ")");
    } else {
        $resources = $db->select("clist_resource", "*", "enable = $enable");
    }

    echo "<i>" . date("r") . "</i><br><br>\n\n";

    $resources_hosts = array();
    foreach ($resources as $resource)
    {
        $start_parsing_time = microtime(true);
        $parse_url = empty($resource['parse_url'])? $resource['url'] : $resource['parse_url'];
        $variables = array(
            '${YEAR}' => date('Y')
        );
        $parse_url = strtr($parse_url, $variables);
        $resources_hosts[$resource['id']] = $resource['host'];


        echo "<b>{$resource['host']}</b>";
        $preCountContests = count($contests);
        if ($resource['path'])
        {
            $HOST_URL = $resource['url'];
            $URL = $parse_url;
            $HOST = $resource['host'];
            $RID = $resource['id'];
            $TIMEZONE = $resource['timezone'];
            $INFO = json_decode($resource['info'], true);

            include $resource['path'];

            unset($HOST_URL);
            unset($URL);
            unset($HOST);
            unset($RID);
            unset($LANG);
            unset($TIMEZONE);
            unset($INFO);
        }
        if ($resource['regexp'])
        {
            $url = $parse_url;

            $page = curlexec($url);

            $page = str_replace("&nbsp;", " ", $page);
            $page = replace_russian_moths_to_number($page);

            preg_match_all($resource['regexp'], $page, $matches,  PREG_SET_ORDER);

            if (DEBUG) {
                print_r($matches);
            }

            $timezone_offset = timezone_offset_get(new DateTimeZone($resource['timezone']), new DateTime("now"));

            $registration = NULL;
            foreach ($matches as $match)
            {
                foreach(
                    array('date', 'date_start_time', 'date_end_time', 'start_date', 'end_date', 'start_time', 'end_time', 'duration', 'url', 'title', 'key')
                    as $param
                ) $match[$param] = isset($match[$param])? trim(($match[$param])) : '';

                if ($match['date'] == "Сегодня") $match['date'] = date("Y-m-d", time() + $timezone_offset);
                if ($match['date'] == "Завтра") $match['date'] = date("Y-m-d", time() + 24 * 60 * 60 + $timezone_offset);

                if ($match['start_date'] && $match['start_time']) $match['start_time'] = $match['start_date'] . ' ' . $match['start_time'];
                if ($match['end_date'] && $match['end_time']) $match['end_time'] = $match['end_date'] . ' ' . $match['end_time'];

                $contest = array(
                    'start_time' => $match['date'] && $match['date_start_time']? $match['date'] . ' ' . $match['date_start_time'] : $match['start_time'],
                    'end_time' => $match['date'] && $match['date_end_time']? $match['date'] . ' ' . $match['date_end_time'] : $match['end_time'],
                    'duration' => $match['duration'],
                    'title' => $match['title'],
                    'url' => $match['url']? $match['url'] : $resource['url']
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

                if (!parse_url($contest['url'], PHP_URL_HOST))
                {
                    $url = empty($resource['parse_url'])? $url : $resource['url'];
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
                $contest['key'] = $match['key']? $match['key'] : ($match['url']? $contest['url'] : '');

                $contests[] = $contest;
            }
        }

        $elapsed_time = microtime(true) - $start_parsing_time;
        $elapsed_time_human_readable = sprintf("%0.3f", $elapsed_time);
        echo " (" . (count($contests) - $preCountContests) . ") [<i title=\"" . human_readable_seconds($elapsed_time) . "\">" . number_format($elapsed_time, 3) . "</i>]<br>\n";
    }

    $last_resource = "";
    $updated_resources = array();
    foreach ($contests as $i => $contest)
    {
        $updated_resources[$contest['rid']] = true;
        foreach (array('start_time', 'end_time') as $k) {
            if (isset($contest[$k]) && !is_numeric($contest[$k]) && $contest[$k]) {
                if (!preg_match('/(?:[\-\+][0-9]+:[0-9]+|\s[A-Z]{3,})$/', $contest[$k]) and strpos($contest[$k], $contest['timezone']) === false) {
                    $contest[$k] .= " ". $contest['timezone'];
                }
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

        if (isset($contest['duration']) && ($contest['duration'] || is_numeric($contest['duration'])))
        {
            if (preg_match('#^(?:(?<d>\d+)d)?(?:\s*(?<hr>\d+)(?:hr|h))?(?:\s*(?<min>\d+)(?:min|m))?#', $contest['duration'], $match) && $match[0]) {
                foreach (array('d', 'hr', 'min') as $arg)
                    if (!isset($match[$arg]) || empty($match[$arg])) $match[$arg] = 0;
                $contest['duration'] = (($match['d'] * 24 + $match['hr']) * 60 + $match['min']) * 60;
            }
            else if (preg_match('#^(\d+):(\d+):(\d+)$#', $contest['duration'], $match))
                $contest['duration'] = (((int)$match[1] * 24 + (int)$match[2]) * 60 + (int)$match[3]) * 60;
            else if (preg_match('#^(\d+):(\d+)$#', $contest['duration'], $match))
                $contest['duration'] = ((int)$match[1] * 60 + (int)$match[2]) * 60;
            else if (preg_match('#^(\d+)$#', $contest['duration'], $match))
                $contest['duration'] = (int)$match[1] * 60;
            else {
                $contest['duration'] = preg_replace('/^([0-9]+)d /', '\1 days ', $contest['duration']);
                $contest['duration'] = strtotime("01.01.1970 " . $contest['duration'] . " +0000");
            }

            if (isset($contest['start_time']) && empty($contest['end_time'])) $contest['end_time'] = $contest['start_time'] + $contest['duration'];
            if (empty($contest['start_time']) && isset($contest['end_time'])) $contest['start_time'] = $contest['end_time'] - $contest['duration'];
        }

        $contests[$i] = $contest;
    }

    $by_key = [];
    foreach ($contests as $i => $contest)
    {
        if (!isset($contest['skip_update_key']) || !$contest['skip_update_key']) {
            switch ($contest['host']) {
                case 'dl.gsu.by': $contest['key'] = $contest['title'] . '. ' . date("d.m.Y", $contest['start_time']); break;
                case 'neerc.ifmo.ru/trains': $contest['key'] = $contest['title'] . date(" d.m.Y", $contest['start_time']); break;
            }
        }

        foreach(
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

    foreach ($contests as $i => $contest)
    {
        //$timezone_offset = timezone_offset_get(new DateTimeZone($contest['timezone']), new DateTime("now"));
        //$contest['start_time'] -= $timezone_offset;
        //$contest['end_time'] -= $timezone_offset;

        $contest['title'] = strip_tags(html_entity_decode($contest['title']));
        $contest['title'] = preg_replace_callback(
            "/(&#[0-9]+;)/",
            function($m) {
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
            if ($contest['end_time'] < $contest['start_time']) continue;
            if ($contest['end_time'] + 31 * 24 * 60 * 60 < time()) continue;
        }

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
        $contest_rid = $contest['rid'];

        $duplicate = isset($contest['duplicate']) && $contest['duplicate'];

        unset($contest['duration']);
        unset($contest['timezone']);
        unset($contest['rid']);
        unset($contest['duplicate']);
        unset($contest['skip_check_time']);
        unset($contest['skip_update_key']);
        unset($contest['delete_after_end']);

        $info = false;
        if (isset($contest['info'])) {
            $info = json_encode($contest['info'], JSON_HEX_APOS);
        }
        unset($contest['info']);


        $contest = $db->escapeArray($contest);

        if (isset($contest['old_key'])) {
            $old_key = $contest['old_key'];
            unset($contest['old_key']);
            $key = $contest['key'];

            $old_update = "$update and key = '${old_key}'";
            if (!$db->query("UPDATE clist_contest SET key = '$key' WHERE $old_update", true)) {
                $db->query("DELETE FROM clist_contest WHERE $old_update", true);
            }
        }

        $contest['was_auto_added'] = 1;

        foreach ($contest as $field => $value)
        {
            $fields .= ",$field";
            $values .= ",'$value'";
            if ($contest['host'] == 'stats.ioinformatics.org' && $field == 'duration_in_secs') {
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
        if ($to_update) {
            if ($to_delete) {
                $db->query("DELETE FROM clist_contest WHERE resource_id = ${contest_rid} and key = '${contest['key']}'", true);
            } else {
                $db->query("INSERT INTO clist_contest ($fields) values ($values) ON CONFLICT (resource_id, key) DO UPDATE SET $update");
            }
        }

        $resource_host = $resources_hosts[$contest_rid];
        if ($last_resource != $resource_host) {
            echo "<br><b>$resource_host</b>:<br>\n";
            $last_resource = $resource_host;
        }

        $duration_human = human_readable_seconds($contest['duration_in_secs']);
        echo "\t<span style='padding-left: 50px'>" .
            ($duplicate? "<i>duplicate</i> " : "") .
            ($to_update? "" : "<i>skip</i> ") .
            ($to_delete? "<i>delete</i> " : "") .
            "{$contest['title']} ({$contest['start_time']} | $duration_human) [{$contest['key']}]</span><br>\n";
    }
    if (count($updated_resources)) {
        $query =
            'was_auto_added = true'
            . ' AND resource_id IN (' . implode(',', array_keys($updated_resources)) . ')'
            . " AND start_time > now() AND now() - interval '2 hours' > updated";
        $to_be_removed = $db->select("clist_contest", "*", $query);
        if ($to_be_removed) {
            $filename_log =  LOGREMOVEDDIR . date("Y-m-d_H-i-s", time()) . '.txt';
            file_put_contents($filename_log, print_r($to_be_removed, true));

            echo "<br><br><b><font color='red'>To be removed</font></b>:<br>\n";
            foreach ($to_be_removed as $contest) {
                echo "\t<span style='padding-left: 50px'>" .
                    "{$contest['title']} [{$contest['key']}] <{$contest['url']}></span><br>\n";
            }
            if (!DEBUG) {
                $db->delete("clist_contest", $query);
            }
        }
    }
    logmsg();
?>
