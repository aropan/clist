<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);

    preg_match_all('#<script[^>]*src="(?P<src>[^"]*\.js)"[^>]*>#', $page, $matches);
    $seen = array();
    foreach ($matches['src'] as $script_src) {
        $script_data = curlexec($script_src);
        if (!preg_match('#"(?P<url>[^"]*timeanddate[^"]*\bcodesprint[^&]*la\b[^&]*\b(?P<year>[0-4]{4})\b[^"]*)"#i', $script_data, $match)) {
            continue;
        }

        function add_standings_url($year, $standings_url) {
            global $HOST, $RID, $TIMEZONE;
            global $contests, $seen, $found;

            if (!preg_match('#https?://[^/]*kattis.com/#', $standings_url)) {
                return;
            }

            $url = preg_replace('#/standings/?#', '', $standings_url);
            $standings_url = $url . '/standings';

            $contest_page = curlexec($url);
            preg_match_all('#<td[^>]*>(?P<key>[^<]*)</td>\s*<td[^>]*>(?P<value>[^<]*)</td>#', $contest_page, $values, PREG_SET_ORDER);
            $values_data = array();
            foreach ($values as $value) {
                $values_data[slugify($value['key'])] = trim($value['value']);
            }

            if (!isset($values_data['start-time']) || !isset($values_data['end-time'])) {
                return;
            }

            preg_match('#<h1>(?P<title>[^<]*)</h1>#', $contest_page, $title_match);
            $title = $title_match['title'];

            $contests[] = array(
                'start_time' => strtotime($values_data['start-time']),
                'end_time' => strtotime($values_data['end-time']),
                'title' => $title,
                'url' => $url,
                'standings_url' => $standings_url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => preg_replace('#https?://#', '', $url),
                'delete_key' => !isset($seen[$year])? $year : null,
            );
            $seen[$year] = true;
        }

        preg_match_all('#\b(?P<year>[0-9]{4})\b:\s*(?P<json>{[^}]*})#', $script_data, $past, PREG_SET_ORDER);
        foreach ($past as $p) {
            $data = json_decode($p['json'], true);
            $year = $p['year'];
            foreach ($data as $_ => $standings_url) {
                add_standings_url($year, $standings_url);
            }
            if (isset($seen[$year]) && !isset($_GET['parse_full_list'])) {
                break;
            }
        }

        $year = $match['year'];
        $current_standings_regex = '#"(?P<url>https?://[^"]*codesprintla' . substr($year, 2) . '[^"]*)"#';
        preg_match_all($current_standings_regex, $script_data, $current_standings);
        foreach ($current_standings['url'] as $standings_url) {
            add_standings_url($year, $standings_url);
        }

        if (isset($seen[$year])) {
            break;
        }

        $parsed_url = parse_url($match['url']);
        parse_str($parsed_url['query'], $query_params);

        $title = $query_params['msg'];

        $start_iso = $query_params['iso'];
        if (preg_match('#T[0-9]{2}$#', $start_iso)) {
            $start_iso .= ':00:00';
        }
        $start_time = strtotime($start_iso);
        $end_time = null;
        $duration_in_seconds = ($query_params['ah'] ?? 0) * 60 + ($query_params['am'] ?? 0);

        $start_date_time = preg_replace('#T.*#', '', $start_iso);
        preg_match_all('#"(?P<start_time>[0-9]{1,2}:[0-9]{2}\s*[AP]M)\s*-\s*(?P<end_time>[0-9]{1,2}:[0-9]{2}\s*[AP]M)\s*(?P<timezone>[A-Z]{3})"#', $script_data, $times, PREG_SET_ORDER);
        foreach ($times as $t) {
            $duration = strtotime($t['end_time']) - strtotime($t['start_time']);
            if ($duration == 5 * 60 * 60) { // 5 hours
                $start_time = strtotime($start_date_time . " " . $t['start_time'] . ' ' . $t['timezone']);
                $end_time = strtotime($start_date_time . " " . $t['end_time'] . ' ' . $t['timezone']);
                $duration_in_seconds = null;
                break;
            }
        }

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration' => $duration_in_seconds,
            'title' => $title,
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $year,
        );

        break;
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
