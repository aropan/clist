<?php
    require_once dirname(__FILE__) . "/../../config.php";


    $near_season = date('Y') - 2022;
    $seen = array();
    for ($season = $near_season; $season <= $near_season + 1; $season += 1) {
        $stage_standings_url = "https://ucup.ac/rating?season=$season";
        $rating_page = curlexec($stage_standings_url);
        preg_match_all('#<th[^>]*>\s*<a[^>]*href="(?P<href>[^"]*)"[^>]*>(?P<title>[^<]*)</a>\s*</th>#s', $rating_page, $matches, PREG_SET_ORDER);
        $standings = array();
        foreach ($matches as $stage => $th) {
            $standings_url = url_merge($stage_standings_url, $th['href']);
            $parsed_url = parse_url($standings_url);
            $parsed_url['path'] = rtrim($parsed_url['path'], '/') . '/standings/';
            $standings_url = unparse_url($parsed_url);
            $standings[$stage] = array("standings_url" => $standings_url, "title" => $th['title'], "stage" => $stage);
        }

        $stage_url = "https://ucup.ac/?season=$season";
        $schedule_page = curlexec($stage_url);

        if (!preg_match('#<h1[^>]*>[^<]*\bseason\b\s*\b' . $season . '\b[^<]*</h1>#i', $schedule_page)) {
            continue;
        }

        $stage_start_time = null;
        $stage_end_time = null;

        preg_match_all('#<tr>.*?</tr>#s', $schedule_page, $rows, PREG_SET_ORDER);
        $headers = false;
        foreach ($rows as $row) {
            preg_match_all('#<t[hd][^>]*>(?P<values>.*?)</(?P<tag>t[hd])>#s', $row[0], $cols);
            if ($headers === false || $cols['tag'][0] == 'th') {
                $headers = array_map('strtolower', $cols['values']);
                continue;
            }

            $values = $cols['values'];
            foreach ($values as &$value) {
                if (preg_match('#<a[^>]*href="(?P<href>[^"]*)"[^>]*>#', $value, $match)) {
                    $value = url_merge($stage_url, $match['href']);
                }
                $value = preg_replace('#<[^?]*>.*$#', '', $value);
                $value = trim($value);
            }
            $min_count = min(count($headers), count($values));
            $c = array_combine(
                array_slice($headers, 0, $min_count),
                array_slice($values, 0, $min_count),
            );

            if (!isset($c['stage']) || !isset($c['contest']) || !isset($c['date']) || !isset($c['scoreboard'])) {
                continue;
            }

            $title = "The " . ordinal($season) . " Universal Cup. Stage {$c['stage']}: " . trim($c['contest']);
            $date = $c['date'];

            if (strpos($date, 'TBD') !== false) {
                continue;
            }

            if (strpos($date, "to") !== false) {
                $date = trim(explode("to", $date)[0]);
            }

            $parts = explode('.', $date);
            if (strlen($parts[0]) == 4) {
                $parts = array_reverse($parts);
            }
            $date = implode('.', $parts);

            // $season = date('Y', strtotime($date)) - 2022 + (date('m', strtotime($date)) >= 9? 1 : 0);
            $start_time = $date . ' 05:00 UTC';
            $end_time = $date . ' 23:00 UTC';
            $duration = '05:00';
            $key = 'ucup-' . $season . '-stage-' . $c['stage'];
            $info = array('parse' => array('season' => "$season", 'stage' => $c['stage']));

            $standings_url = $c['scoreboard'];
            $standings_stage = null;
            foreach ($standings as $stage => $info) {
                if (stripos($info['title'], $c['contest']) === false) {
                    continue;
                }
                if ($standings_stage === null || strlen($info['title']) < strlen($standings_stage['title'])) {
                    $standings_stage = $info;
                }
            }
            if ($standings_stage) {
                $standings_url = $standings_stage['standings_url'];
                unset($standings[$standings_stage['stage']]);
            }

            $start_and_title = $start_time . " " . $c['stage'] . " " . trim($c['contest']);
            if (isset($seen[$start_and_title])) {
                continue;
            }
            $seen[$start_and_title] = true;

            if ($stage_start_time === null) {
                $stage_start_time = $start_time;
            }
            $stage_end_time = $end_time;

            $contest = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'duration' => $duration,
                'title' => trim($title),
                'url' => isset($c['announcement'])? $c['announcement'] : $stage_url,
                'standings_url' => $standings_url,
                'key' => $key,
                'info' => $info,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'rid' => $RID,
            );

            $contests[] = $contest;
        }

        $two_weeks = 14 * 24 * 60 * 60;
        $stage_end_time = strtotime($stage_end_time) + $two_weeks;
        $contest = array(
            'start_time' => $stage_start_time,
            'end_time' => $stage_end_time,
            'title' => "The " . ordinal($season) . " Universal Cup. Rating",
            'url' => $stage_url,
            'standings_url' => $stage_standings_url,
            'key' => 'ucup-' . $season . '-rating',
            'info' => array('_inherit_stage' => true),
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
        $contests[] = $contest;
    }
?>
