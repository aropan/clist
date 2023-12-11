<?php
    require_once dirname(__FILE__) . "/../../config.php";


    $near_season = date('Y') - 2022;
    for ($season = $near_season; $season <= $near_season + 1; $season += 1) {
        $url = "https://ucup.ac/rating?season=$season";
        $rating_page = curlexec($url);
        preg_match_all('#<th[^>]*>\s*<a[^>]*href="(?P<href>[^"]*)"[^>]*>(?P<title>[^<]*)</a>\s*</th>#s', $rating_page, $matches, PREG_SET_ORDER);
        $standings = array();
        foreach ($matches as $stage => $th) {
            $standings_url = url_merge($url, $th['href']);
            $parsed_url = parse_url($standings_url);
            $parsed_url['path'] = rtrim($parsed_url['path'], '/') . '/standings/';
            $standings_url = unparse_url($parsed_url);
            $standings[$stage] = array("standings_url" => $standings_url, "title" => $th['title'], "stage" => $stage);
        }

        $url = "https://ucup.ac/?season=$season";
        $schedule_page = curlexec($url);

        preg_match_all('#<tr>.*?</tr>#s', $schedule_page, $rows, PREG_SET_ORDER);
        $headers = false;
        foreach ($rows as $row) {
            preg_match_all('#<t[hd][^>]*>(.*?)</t[hd]>#s', $row[0], $cols);
            if ($headers === false) {
                $headers = array_map('strtolower', $cols[1]);
                continue;
            }

            $values = $cols[1];
            foreach ($values as &$value) {
                if (preg_match('#<a[^>]*href="(?P<href>[^"]*)"[^>]*>#', $value, $match)) {
                    $value = url_merge($url, $match['href']);
                }
                $value = preg_replace('#<[^?]*>.*$#', '', $value);
                $value = trim($value);
            }
            $min_count = min(count($headers), count($values));
            $c = array_combine(
                array_slice($headers, 0, $min_count),
                array_slice($values, 0, $min_count),
            );

            $title = "The " . ordinal($season) . " Universal Cup. Stage {$c['stage']}: " . trim($c['contest']);
            $date = $c['date'];

            if (strpos($date, 'TBD') !== false) {
                continue;
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

            $contest = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'duration' => $duration,
                'title' => trim($title),
                'url' => isset($c['announcement'])? $c['announcement'] : $url,
                'standings_url' => $standings_url,
                'key' => $key,
                'info' => $info,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'rid' => $RID,
            );

            $contests[] = $contest;
        }
    }
?>
