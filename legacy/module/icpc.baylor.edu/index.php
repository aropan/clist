<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    unset($xwiki);
    if (preg_match('#src="(?P<js>/static/js/main.[^"]*.js)"#', $page, $match)) {
        $page = curlexec($match['js']);
        if (!preg_match('#XWIKI:"(?P<xwiki>[^"]*)"#', $page, $match)) {
            trigger_error('Not found xwiki', E_USER_WARNING);
            return;
        }
        $xwiki = url_merge($URL, '/' . trim($match['xwiki'], '/'));
        $url = "$xwiki/virtpublic/worldfinals/schedule";

        $page = curlexec($url);
    }

    if (!preg_match("#>The (?P<year>[0-9]{4}) (?P<title>(?:ACM-)?ICPC World Finals)#i", $page, $match)) {
        trigger_error('Not found year and title', E_USER_WARNING);
        return;
    }

    $year = $match['year'];
    $title = trim($match['title']);

    if (!preg_match("#>hosted by\s+(?:the\s+)(?:[^,<]*,)?\s*(?P<where>[^<]*?)\s*<#i", $page, $match)) {
        trigger_error('Not found where', E_USER_WARNING);
        return;
    }
    $where = $match['where'];

    $duration = '24 hours';
    $duration_in_secs = 5 * 60 * 60;
    if (preg_match('#.*(?P<day><th[^>]*colspan[^>]*>\s*[a-z]+\s*(?P<date>[^<]*)&[^<]*'. $title . '[^<]*</th>.*?)<th[^>]*colspan[^>]*>#is', $page, $match)) {
        $start_date = trim($match['date']) . ' ' . $year;
        preg_match_all('#(?P<times>(?:<td[^>]*>[^<]*</td>\s*)+)<td[^>]*required[^>]*>#s', $match['day'], $matches, PREG_SET_ORDER);
        $opt = 1e9;
        $opt_start_time = false;
        foreach ($matches as $m) {
            $times = $m['times'];
            if (preg_match_all('#<td[^>]*>(?P<time>[^<]+)</td>#', $times, $matches) && count($matches['time']) == 2) {
                list($start_time, $end_time) = $matches['time'];
                $duration_time = strtotime($end_time) - strtotime($start_time);
                $diff = abs($duration_time - $duration_in_secs);
                if ($diff < $opt) {
                    $opt = $diff;
                    $duration = $duration_time / 60;
                    $opt_start_time = trim($start_time);
                }
            }
        }
        if ($opt_start_time) {
            $start_date = $start_date . ' ' . $opt_start_time;
        }
    } else if (preg_match("#held on (?P<date>[^,\.<]*)#", $page, $match)) {
        $start_date = $match['date'] . ' ' . $year;
    } else {
        trigger_error('Not found date', E_USER_WARNING);
        return;
    }

    if ($where == 'AASTMT') {
        $title .= ". $where, Egypt";
        $timezone = 'Africa/Cairo';
        $start_date = str_replace($year, $year + 1, $start_date);
    } else if (starts_with($where, 'Kazakhstan')) {
        $title .= ". $where";
        $timezone = 'Asia/Almaty';
    } else {
        $title .= ". $where";
        $timezone = $TIMEZONE;
    }

    $contests[] = array(
        'start_time' => $start_date,
        'duration' => $duration,
        'duration_in_secs' => $duration_in_secs,
        'title' => $title,
        'url' => $URL,
        'host' => $HOST,
        'key' => $year,
        'rid' => $RID,
        'timezone' => $timezone
    );

    $parse_full_list = isset($_GET['parse_full_list']);
    for (;$parse_full_list && isset($xwiki) && $year > 1970;) {
        --$year;
        $path = "/community/history-icpc-$year";

        $url = "$xwiki/$path";
        $page = curlexec($url);
        $url = url_merge($URL, $path);

        if (strpos($page, "page not found") !== false) {
            break;
        }

        if (preg_match("#[A-Z][a-z]* [0-9]+(?:-[0-9]+)?, $year#", $page, $match)) {
            $page = str_replace($match[0], '', $page);
            $time = preg_replace('#-[0-9]+#', '', $match[0]);
        } else {
            $time = "02.01.$year";
        }

        if (preg_match_all("#[Tt]he(?P<title>(?:\s+[A-Z0-9][A-Za-z0-9]*)+)#", $page, $matches)) {
            $title = "";
            foreach ($matches['title'] as $t) {
                if (strlen($t) > strlen($title)) {
                    $title = $t;
                }
            }
            if (strpos($title, "World Champions") !== false) {
                $title = "The " . ($year - 1976) . "th Annual ACM ICPC World Finals";
            } else {
                $title = preg_replace('#International Collegiate Programming Contest#i', 'ICPC', $title);
            }
        } else {
            $title = "World Finals";
        }
        if (preg_match("# in\s*(?:<[^>]*>\s*)?(?P<name>[A-Z][A-Za-z.]+(?:,?\s*[A-Z][A-Za-z.]+)*)#", $page, $match)) {
            $title .= ". " . trim($match['name'], '.');
        }

        $contests[] = array(
            'start_time' => $time,
            'duration' => '24 hours',
            'duration_in_secs' => 5 * 60 * 60,
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'key' => $year,
            'rid' => $RID,
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
