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

    foreach ($resources as $resource)
    {
        echo "<b>{$resource['host']}</b>";
        $preCountContests = count($contests);
        if ($resource['path'])
        {
            $URL = $resource['url'];
            $HOST = $resource['host'];
            $RID = $resource['id'];
            $TIMEZONE = $resource['timezone'];

            include $resource['path'];

            unset($URL);
            unset($HOST);
            unset($RID);
            unset($LANG);
            unset($TIMEZONE);
        }
        if ($resource['regexp'])
        {
            $variables = array(
                '${YEAR}' => date('Y')
            );
            $url = strtr($resource['url'], $variables);

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
                    array('date', 'date_start_time', 'date_end_time', 'start_time', 'end_time', 'duration', 'url', 'title', 'key')
                    as $param
                ) $match[$param] = isset($match[$param])? trim(($match[$param])) : '';

                if ($match['date'] == "Сегодня") $match['date'] = date("Y-m-d", time() + $timezone_offset);
                if ($match['date'] == "Завтра") $match['date'] = date("Y-m-d", time() + 24 * 60 * 60 + $timezone_offset);

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

                if ($resource['host'] == 'projecteuler.net' && strpos(parse_url($contest['url'], PHP_URL_HOST), $resource['host']) === false) {
                    $contest['url'] = 'http://' . $resource['host'] . '/';
                }

                if ($resource['host'] == 'stats.ioinformatics.org') {
                    $contest['url'] = '/' . $contest['url'];
                }

                if ($resource['host'] == 'acm.hdu.edu.cn' && empty($contest['duration']))
                    $contest['duration'] = '05:00';
                if ($resource['host'] == 'projecteuler.net' && empty($contest['duration']))
                    $contest['duration'] = '00:00';
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
                )
                    continue;

                if (!parse_url($contest['url'], PHP_URL_HOST))
                {
                    if ($contest['url'][0] == '/')
                        $contest['url'] = 'http://' . parse_url($url, PHP_URL_HOST) . $contest['url'];
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
        echo "(" . (count($contests) - $preCountContests) . " of " . count($contests) . ")<br>\n";
    }

    $lastresources = "";
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

        if (isset($contest['duration']) && $contest['duration'])
        {
            if (preg_match('#^(?:(?<d>\d+)d)?(?:\s*(?<hr>\d+)hr)?(?:\s*(?<min>\d+)min)?#', $contest['duration'], $match) && $match[0])
            {
                foreach (array('d', 'hr', 'min') as $arg)
                    if (!isset($match[$arg])) $match[$arg] = 0;
                $contest['duration'] = (($match['d'] * 24 + $match['hr']) * 60 + $match['min']) * 60;
            }
            else
            if (preg_match('#^(\d+):(\d+):(\d+)$#', $contest['duration'], $match))
                $contest['duration'] = (((int)$match[1] * 24 + (int)$match[2]) * 60 + (int)$match[3]) * 60;
            else
            if (preg_match('#^(\d+):(\d+)$#', $contest['duration'], $match))
                $contest['duration'] = ((int)$match[1] * 60 + (int)$match[2]) * 60;
            else
            if (preg_match('#^(\d+)$#', $contest['duration'], $match))
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
        switch ($contest['host'])
        {
            case 'dl.gsu.by': $contest['key'] = $contest['title'] . '. ' . date("d.m.Y", $contest['start_time']); break;
            case 'topcoder.com': $contest['key'] = $contest['title'] . '. ' . date("d.m.Y", $contest['start_time']); break;
            case 'neerc.ifmo.ru/trains': $contest['key'] = $contest['title'] . date(" d.m.Y", $contest['start_time']); break;
        }

        foreach(
            array('start_time', 'end_time', 'duration', 'url', 'title', 'key')
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

    foreach ($contests as $i => $contest)
    {
        //$timezone_offset = timezone_offset_get(new DateTimeZone($contest['timezone']), new DateTime("now"));
        //$contest['start_time'] -= $timezone_offset;
        //$contest['end_time'] -= $timezone_offset;

        if (time() + 365 * 24 * 60 * 60 < $contest['end_time']) continue;
        if (!DEBUG && !isset($_GET['skip_check_time'])) {
            if ($contest['end_time'] < $contest['start_time']) continue;
            if ($contest['end_time'] + 31 * 24 * 60 * 60 < time()) continue;
        }

        if (!isset($contest['key']) || !$contest['key']) $contest['key'] = date("Y", $contest['start_time']) . " " . $contest['title'];

        if (isset($contest['duration_in_secs'])) {
            $contest['end_time'] += $contest['duration_in_secs'];
        }
        $contest['duration_in_secs'] = $contest['end_time'] - $contest['start_time'];
        $contest['start_time'] = date('Y-m-d H:i:s', $contest['start_time']);
        $contest['end_time'] = date('Y-m-d H:i:s', $contest['end_time']);

        $fields = "resource_id";
        $values = $contest['rid'];
        $update = "resource_id = " . $contest['rid'];

        $duplicate = isset($contest['duplicate']) && $contest['duplicate'];

        unset($contest['duration']);
        unset($contest['timezone']);
        unset($contest['rid']);
        unset($contest['duplicate']);

        $contest = $db->escapeArray($contest);

        $contest['was_auto_added'] = 1;

        foreach ($contest as $field => $value)
        {
            $fields .= ",$field";
            $values .= ",'$value'";
            $update .= ",$field='$value'";
        }

        $now = date("Y-m-d H:i:s", time());
        //$fields .= ",created";
        //$values .= ",'$now'";
        //$fields .= ",modified";
        //$values .= ",'$now'";
        if (!DEBUG) {
            $db->query("INSERT INTO clist_contest ($fields) values ($values) ON CONFLICT (resource_id, key) DO UPDATE SET $update");
        }

        if ($lastresources != $contest['host']) {
            echo "<br><br><b>{$contest['host']}</b>:<br>\n";
            $lastresources = $contest['host'];
        }

        $duration_human = secs_to_h($contest['duration_in_secs']);
        echo "\t<span style='padding-left: 50px'>" .
            ($duplicate? "<i>duplicate</i> " : "") .
            "{$contest['title']} ({$contest['start_time']} | $duration_human) [{$contest['key']}]</span><br>\n";
    }
    if (count($updated_resources)) {
        $query =
            'was_auto_added = true'
            . ' AND resource_id IN (' . implode(',', array_keys($updated_resources)) . ')'
            . " AND end_time - interval '1 day' > now() AND now() - interval '1 day' > updated";
        $to_be_removed = $db->select("clist_contest", "*", $query);
        if ($to_be_removed) {
            $dir = 'logs/removed/';
            mkdir($dir);
            chmod($dir, 0775);
            $filename_log =  $dir . date("Y-m-d_H-i-s", time()) . '.txt';
            file_put_contents($filename_log, print_r($to_be_removed, true));

            echo "<br><br><b><font color='red'>To be removed</font></b>:<br>\n";
            foreach ($to_be_removed as $contest) {
                echo "\t<span style='padding-left: 50px'>" .
                    "{$contest['title']} [{$contest['key']}] <{$contest['url']}></span><br>\n";
            }
            $db->delete("clist_contest", $query);
        }
    }
    logmsg();
?>
