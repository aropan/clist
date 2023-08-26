<?php
    require_once dirname(__FILE__) . "/../../config.php";


    $near_season = date('Y') - 2022;
    for ($season = $near_season; $season <= $near_season + 1; $season += 1) {
        $URL = "https://ucup.ac/?season=$season";
        $schedule_page = curlexec($URL);

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
                    $value = $match['href'];
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

            $contest = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'duration' => $duration,
                'title' => trim($title),
                'url' => isset($c['announcement'])? $c['announcement'] : $URL,
                'standings_url' => $c['scoreboard'],
                'key' => $key,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'rid' => $RID,
            );

            $contests[] = $contest;
        }
    }
?>
