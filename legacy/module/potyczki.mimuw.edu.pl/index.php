<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = $HOST_URL;
    $page = curlexec($url);

    $parsed_times = array();
    $parsed_year = null;
    if (preg_match('#<div[^>]*news_text[^>]*>.*?(?P<year>20[0-9]{2})#s', $page, $match)) {
        $parsed_year = $match['year'];

        function rename_months_from_pl_to_en($page, $year) {
            $month_dict = array(
                "st" => "january",
                "lu" => "february",
                "mar" => "march",
                "kw" => "april",
                "maj" => "may",
                "cz" => "june",
                "lip" => "july",
                "si" => "august",
                "wr" => "september",
                "pa" => "october",
                "lis" => "november",
                "gru" => "december",
            );
            foreach ($month_dict as $key => $value) {
                $value .= ' ' . $year;
                $page = preg_replace('#\b' . $key . '\w*#', $value, $page);
            }
            return $page;
        }
        $page = rename_months_from_pl_to_en($page, $parsed_year);
        $page = preg_replace('#\s*godz.\s*#', ' ', $page);

        preg_match_all('#
            <tr[^>]*>\s*
                <td[^>]*>\s*(?P<round>[0-9])\s*</td>\s*
                <td[^>]*>(?P<start_time>[^<]*)</td>\s*
                <td[^>]*>(?P<end_time>[^<]*)</td>\s*
                (?:\s*<td[^>]*>[^<]*</td>){3}\s*
            </tr>
            #x',
            $page,
            $matches,
            PREG_SET_ORDER,
        );

        foreach ($matches as $m) {
            $name = 'Runda ' . $m['round'];
            $start_time = $m['start_time'] . ' ' . $TIMEZONE;
            $end_time = $m['end_time'] . ' ' . $TIMEZONE;
            $parsed_times[$name] = array('start_time' => $start_time, 'end_time' => $end_time);
        }
    }

    $year = date('Y');
    $url = $URL;

    do {
        $page = curlexec($url);
        $standings_url = str_replace('/p/', '/ranking/', $url);

        if (!preg_match_all('#<tr[^>]*problemlist-subheader[^>]*>\s*<td[^>]*>(?P<info>.*?)</td>#ms', $page, $matches)) {
            break;
        }

        if (!preg_match('#<div[^>]*class="contest-name"[^>]*>(?P<name>[^<]*)</div>#', $page, $match)) {
            trigger_error("Not found contest name in $url", E_USER_WARNING);
            return;
        }
        $name = $match['name'];

        $prev_time = false;
        $stage_start_time = null;
        $stage_end_time = null;

        foreach ($matches['info'] as $info) {
            $info = preg_replace('#<[^>]*>#', "\n", $info);
            $info = trim($info);
            list($round, $end_time) = preg_split('#\n[\s]*#', $info);
            $round = trim($round, '.');
            $end_time = trim($end_time, '()');
            if (!preg_match('#^Runda [0-9]$#', $round)) {
                continue;
            }
            $title = $name . '. ' . $round;
            $end_time .= ' ' . $TIMEZONE;

            $curr_time = strtotime($end_time);
            if (!$prev_time) {
                $duration = 36 * 60 * 60;  # 36 hours
            } else {
                $duration = $curr_time - $prev_time + 12 * 60 * 60;  # + 12 hours
            }
            $prev_time = $curr_time;

            $start_time = $curr_time - $duration;
            $start_time = round($start_time / 3600) * 3600;

            if ($year == $parsed_year && isset($parsed_times[$round])) {
                $t = $parsed_times[$round];
                $start_time = $t['start_time'];
                $end_time = $t['end_time'];
                unset($parsed_times[$round]);
            }

            $contests[] = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'standings_url' => $standings_url,
                'title' => $title,
                'url' => $url,
                'key' => $title,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'rid' => $RID,
            );

            $stage_start_time = $stage_start_time ?? $start_time;
            $stage_end_time = $end_time ?? $stage_end_time;

        }

        if ($stage_start_time) {
            $contests[] = array(
                'start_time' => $stage_start_time,
                'end_time' => $stage_end_time,
                'start_time_shift' => '-1 hour',
                'end_time_shift' => '+1 day',
                'title' => $name,
                'url' => $HOST_URL,
                'key' => slugify($name),
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'rid' => $RID,
                'info' => array('_inherit_stage' => true),
            );
        }

        $url = str_replace($year, $year - 1, $url);
        $year -= 1;
    } while (isset($_GET['parse_full_list']));
?>
