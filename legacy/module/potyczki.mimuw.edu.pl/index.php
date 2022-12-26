<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = $HOST_URL;
    $page = curlexec($url);

    if (preg_match('#<div[^>]*news_text[^>]*>.*?(?P<year>20[0-9]{2})#s', $page, $match)) {
        preg_match_all('#
            <tr[^>]*>\s*
                <td[^>]*>\s*(?P<round>[0-9])\s*</td>\s*
                <td[^>]*>(?P<start_date>[^<]*)</td>\s*
                <td[^>]*>(?P<end_date>[^<]*)</td>\s*
                (?:\s*<td[^>]*>[^<]*</td>){3}\s*
            </tr>
            #x',
            $page,
            $matches,
            PREG_SET_ORDER,
        );
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
        }

        $url = str_replace($year, $year - 1, $url);
        $year -= 1;
    } while (isset($_GET['parse_full_list']));
?>
