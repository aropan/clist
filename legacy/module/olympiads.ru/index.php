<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $urls = array();
    $urls[] = $URL;

    if (isset($_GET['parse_full_list'])) {
        $page = curlexec($URL);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]+/[0-9]+<#', $page, $matches);
        foreach ($matches['url'] as $url) {
            $urls[] = url_merge($URL, $url);
        }
    }

    $DAY = 24 * 60 * 60;
    $MONTH = 30 * 24 * 60 * 60;
    $YEAR = 364 * 24 * 60 * 60;

    $replace_months = function($page) {
        $amonths = array("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр");
        $replace_pairs = array();
        $replacements = array();
        $subjects = array();
        foreach ($amonths as $ind => $month)
        {
            $month = $month . '[^\s<]{0,3}';
            $ind = sprintf("%02d", $ind + 1);

            $replacements[] = '#([0-9]+)\s' . $month . '\s?#';
            $subjects[] = '\1.' . $ind . '.';

            $replacements[] = '#' . $month . '\s#';
            $subjects[] = $ind . '.';
        }
        $page = preg_replace($replacements, $subjects, $page);
        return $page;
    };

    foreach ($urls as $url) {
        if (DEBUG) {
            echo "\n\n" . $url. "\n";
        }
        $page = curlexec($url);
        $page = $replace_months($page);

        if (!preg_match('#<h4\s*align="center"\s*>(?P<title>[^<]*,[^<]*)<#', $page, $match)) {
            continue;
        }
        list($main_title, $season) = explode(",", $match['title']);
        $main_title = trim($main_title);
        $season = str_replace("/", "-20", explode(" ", trim($season))[0]);

        preg_match_all('#<p>\s*<font[^>]*>\s*(?:[0-9]+-)?(?P<date>(?:[0-9]+.?)+)[^<]*</font>[^<]*(?:<a[^>]*>[^<]*</a>[^<]*)*<a[^>]*href="(?P<url>[^"]*/[^"]*(?:res|standing)[^"]*)"[^>]*>[^<]*результат[^<]*</a>#', $page, $matches, PREG_SET_ORDER);

        $standings = array();
        $used = array();
        $matches = array_reverse($matches);
        foreach ($matches as $match) {
            $u = url_merge($url, $match['url']);
            if (preg_match('#(overall|unrated)#', $u)) {
                continue;
            }
            if (in_array($u, $used)) {
                continue;
            }
            $used[] = $u;

            $h = get_headers($u);
            if (!$h) {
                continue;
            }
            $a = explode(" ", $h[0]);
            $code = $a[1];
            if ($code != 200) {
                continue;
            }
            $date = trim($match['date'], '. ');
            if (substr_count($date, ".") == 1) {
                $years = explode("-", $season);
                $a = explode(".", $date);
                $y = $a[1] < 7? $years[1] : $years[0];
                $date = "$date.$y";
            }
            $standings[] = array(
                "date" => $date,
                "url" => $u,
                "is_final" => (bool)(preg_match("#(final|results[^/]*$|onsite|res-och)#", $u))
            );
            if (DEBUG) {
                echo "$date ::: $u\n";
            }
        }

        if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Информация\s*об\s*олимпиаде\s*</a>#', $page, $match)) {
            continue;
        }
        $page = curlexec($match['url']);
        $page = $replace_months($page);

        preg_match_all("#
            (?P<start_time>(?:(?:[0-9]+\.){1,2}[0-9]+(?:\s+г[^\s]*)?\s*|с\s+[0-9:]+\s*)+)(?:-|по)\s*
            (?P<end_time>(?:(?:[0-9]+\.){1,2}[0-9]+(?:\s+г[^\s]*)?\s*|[0-9:]+\s*)+)
            #x",
            $page,
            $matches
        );

        $long_title ="Заочный длинный этап";
        $short_title ="Заочный короткий тур";
        $final_title = "Заключительный очный этап";
        $titles = [$long_title, $short_title, $final_title];
        $has_final = false;
        foreach ($matches[0] as $i => $value)
        {
            $start_time = $matches["start_time"][$i];
            $end_time = $matches["end_time"][$i];
            $start_time = trim(preg_replace('#[^0-9:.]+[^0-9]*#', ' ', $start_time), '. ');
            $end_time = trim(preg_replace('#[^0-9:.]+[^0-9]*#', ' ', $end_time), '. ');
            $duration = 0;

            if (preg_match('#^[0-9]+$#', $start_time)) {
                $a = explode(".", $end_time);
                $a[0] = $start_time;
                $start_time = implode(".", $a);
            }
            if (strpos($start_time, " ") !== false && strpos($end_time, " ") === false) {
                $a = explode(" ", $start_time);
                $a[count($a) - 1] = $end_time;
                $end_time = implode(" ", $a);
            }
            if (substr_count($start_time, '.') == 1) {
                $start_time = "01.$start_time";
            }
            if (substr_count($end_time, '.') == 1) {
                $end_time = "01.$end_time";
                $duration = $MONTH;
            }
            $duration += strtotime($end_time) - strtotime($start_time) + $DAY;
            $title = $titles[$i];

            if ($duration < -6 * $MONTH) {
                $duration += $YEAR;
            }

            $standings_url = null;

            foreach ($standings as $ind => $s) {
                $date = strtotime($s['date']);
                $end = strtotime($end_time);
                if ($title != $long_title && $date < $end) {
                    continue;
                }
                if (strpos($s['url'], 'short') && $title != $short_title) {
                    continue;
                }
                if ((bool)($title == $final_title) != $s['is_final']) {
                    continue;
                }
                if (DEBUG) {
                    echo $s['date'] . " ### " . $s['url'] . "\n";
                }
                $standings_url = $s['url'];
                unset($standings[$ind]);
                break;
            }

            if (DEBUG) {
                echo $start_time . ' --- '. $end_time . ' --- '. $duration . ' --- ' . $standings_url . "\n";
            }

            $contests[] = array(
                "start_time" => $start_time,
                "duration" => $duration / 60,
                "title" => $title . ". " . $main_title,
                "url" => $url,
                "standings_url" => $standings_url,
                "host" => $HOST,
                "key" => $season . ". " . $title,
                "rid" => $RID,
                "timezone" => $TIMEZONE
            );

            $has_final = $has_final || $title == $final_title;
        }
        if (!$has_final) {
            $standings = array_reverse($standings);
            foreach ($standings as $ind => $s) {
                if (!$s['is_final']) {
                    continue;
                }
                $contests[] = array(
                    "start_time" => $s['date'],
                    "end_time" => $s['date'],
                    "title" => $final_title . ". " . $main_title,
                    "url" => $url,
                    "standings_url" => $s['url'],
                    "host" => $HOST,
                    "key" => $season . ". " . $final_title,
                    "rid" => $RID,
                    "timezone" => $TIMEZONE
                );
                if (DEBUG) {
                    echo '+ ' . $s['date'] . ' --- ' . $s['url'] . "\n";
                }
            }
        }
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
