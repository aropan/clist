<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);

    $amonths = array("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря");
    $replace_pairs = array();
    foreach ($amonths as $ind => $month)
    {
        $ind = sprintf("%02d", $ind + 1);
        $replace_pairs[" $month "] = ".$ind.";
        $replace_pairs[" $month"] = ".$ind." . date('Y');
    }
    $replace_pairs[" феврадя "] = ".02.";

    function replace_months($page) {
        global $replace_pairs;
        return strtr($page, $replace_pairs);
    }

    preg_match_all('#<td class="date">(?<date>\d+\s[^\s]+(?:\s\d+)?)[^<]*</td><td class="time">(?<date_start_time>[^\s<]*)[^<]*</td><td[^>]*>(?<durations>[^<]*)</td><td[^>]*>(?<title>[^<]*)</td>\s*</tr>#', $page, $matches, PREG_SET_ORDER);
    $_contests = [];
    $_timings = [];
    foreach ($matches as $match)
    {
        $title = 'Интернет-олимпиада';
        $match['date'] = replace_months($match['date']);
        $match['date_start_time'] = str_replace('-', ':', $match['date_start_time']);

        $duration = '05:00';
        foreach (explode(',', $match['durations']) as $d) {
            if (strpos($d, "базовая") !== false) {
                continue;
            }
            $duration = explode(' ', trim($d))[0];
            $duration = sprintf("%02d:00", $duration);
        }

        $key = date("Ymd", strtotime($match['date']));

        $_contests[$key] = array(
            'start_time' => trim($match['date']) . ' ' . trim($match['date_start_time']),
            'duration' => '05:00',
            'title' => $title . (!empty($match['title'])? ' (' . $match['title'] . ')' : ''),
            'host' => $HOST,
            'url' => $URL,
            'timezone' => $TIMEZONE,
            'key' => $key,
            'rid' => $RID,
        );
        $_timings[$key] = array(
            'start_time' => trim($match['date']) . ' ' . trim($match['date_start_time']),
            'duration' => '05:00',
        );
    }

    $add_from_seasons = isset($_GET['parse_full_list']);
    preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]{4}-[0-9]{4}</a>#', $page, $matches);
    foreach ($matches['url'] as $url) {
        $url = url_merge($URL, $url);
        $page = curlexec($url);
        preg_match_all('#<h2>(?P<title>[^>]*)</h2>[^<]*(?:<[^>/]*>[^<]*)*<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Результаты#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $u = url_merge($url, $match['url']);
            preg_match('#/(?P<key>20[0-9]{6})/#', $u, $m);
            $key = $m['key'];

            $title = $match['title'];
            list($date, $title) =  preg_split('#[.,] #', $title, 2);
            $date = explode(' ', replace_months($date))[0];
            $title = html_entity_decode($title);

            if (isset($_contests[$key]) && isset($_contests[$key]['standings_url'])) {
                preg_match('#-(?P<subkey>[^-]*)\.[^.-]*$#', $_contests[$key]['standings_url'], $m);
                $new_key = $key . '-' . $m['subkey'];
                $_contests[$new_key] = $_contests[$key];
                $_contests[$new_key]['key'] = $new_key;
            }

            $_contests[$key] = array(
                'start_time' => isset($_timings[$key])? $_timings[$key]['start_time'] : $date,
                'duration' => isset($_timings[$key])? $_timings[$key]['duration'] : '05:00',
                'title' => $title,
                'host' => $HOST,
                'url' => $url,
                'standings_url' => $u,
                'timezone' => $TIMEZONE,
                'key' => $key,
                'rid' => $RID
            );

        }
        if (!$add_from_seasons) {
            break;
        }
    }
    foreach ($_contests as $contest) {
        $contests[] = $contest;
    }
    unset($_contests);

    if ($RID == -1) {
        print_r($contests);
    }
?>
