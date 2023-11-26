<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $urls = array();
    $archive_url = 'https://olympiads.ru/zaoch/';
    $urls[] = $archive_url;

    if (isset($_GET['parse_full_list'])) {
        $page = curlexec($archive_url);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]+/[0-9]+<#', $page, $matches);
        foreach ($matches['url'] as $url) {
            $urls[] = url_merge($archive_url, $url);
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
        $page = preg_replace("#<!--.*?-->#ms", "", $page);
        $page = preg_replace("#<!--.*#ms", "", $page);
        $page = $replace_months($page);

        if (!preg_match('#<h4\s*align="center"\s*>(?P<title>[^<]*,[^<]*)<#', $page, $match)) {
            continue;
        }
        list($main_title, $season) = explode(",", $match['title']);
        $main_title = trim($main_title);
        $season = str_replace("/", "-20", explode(" ", trim($season))[0]);

        preg_match_all('#<p>\s*<font[^>]*>\s*(?:[0-9]+-)?(?P<date>(?:[0-9]+.?)+)[^<]*</font>[^<]*(?:(?:<[^>]*>[^<]*</[^>]*>|<br>)[^<]*)*<a[^>]*href\s*=\s*"(?P<url>[^"]*/[^"]*(?:res|standing)[^"]*)"[^>]*>[^<]*результат[^<]*</a>#', $page, $matches, PREG_SET_ORDER);

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
            if (preg_match('#(final|results[^/]*$|onsite|res-och)#', $u)) {
                $type = 'final';
            } else if (preg_match('#short#', $u)) {
                $type = 'short';
            } else {
                $type = 'long';
            }

            $standings[] = array(
                "date" => $date,
                "url" => $u,
                "type" => $type,
            );
            if (DEBUG) {
                echo "$date ::: $u\n";
            }
        }

        if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Информация\s*об\s*олимпиаде\s*</a>#', $page, $match)) {
            continue;
        }

        $cs = array();

        $page = preg_replace('#<[^>]*>#', '', $page);
        $page = preg_replace('#\([^\)]*\)#', '', $page);
        $page = mb_strtolower($page);
        preg_match_all('#
            (?P<title>длинн|коротк|заключител|\s+очный)[^<\n]*?(?:пройд|прох)[^<\n]*?
            (?P<start_time>(?:(?:[0-9]+\.){1,2}[0-9]+(?:\s+г[^\s]*)?\s*|с\s+[0-9:]+\s*)+)
            (
            (?:-|по|до)\s*
            (?P<end_time>(?:(?:[0-9]+\.){1,2}[0-9]+(?:\s+г[^\s]*)?\s*|[0-9:]+\s*)+)
            (?:[^<\n]*(?P<duration>[0-9]+)[^\s]часо[^\s]*\s*виртуальн)?
            )?
            #xi', $page, $matches, PREG_SET_ORDER,
        );

        foreach ($matches as $m) {
            if (empty($m['end_time'])) {
                $m['end_time'] = $m['start_time'];
            }
            if (isset($m['duration'])) {
                $m['duration'] .= ':00';
            }
            $cs[] = $m;
        }

        $page = curlexec($match['url']);
        $page = $replace_months($page);

        preg_match_all("#
            (?P<title>длинн|коротк|заключител|\s+очный)[^<]*?
            (?P<start_time>(?:(?:[0-9]+\.){1,2}[0-9]+(?:\s+г[^\s]*)?\s*|с\s+[0-9:]+\s*)+)
            (?:-|по|до)\s*
            (?P<end_time>(?:(?:[0-9]+\.){1,2}[0-9]+(?:\s+г[^\s]*)?\s*|[0-9:]+\s*)+)
            #x", $page, $matches, PREG_SET_ORDER,
        );

        foreach ($matches as $m) {
            $cs[] = $m;
        }

        $long_title ="Заочный длинный этап";
        $short_title = "Заочный короткий тур";
        $final_title = "Заключительный очный этап";
        $titles = array(
            "длинн" => $long_title,
            "коротк" => $short_title,
            "заключител" => $final_title,
            "очный" => $final_title,
        );

        $seen = array();

        foreach (array_reverse($cs) as $match) {
            $start_time = $match["start_time"];
            $end_time = $match["end_time"];
            $start_time = trim(preg_replace('#[^0-9:.]+[^0-9]*#', ' ', $start_time), '. ');
            $end_time = trim(preg_replace('#[^0-9:.]+[^0-9]*#', ' ', $end_time), '. ');
            $title = $titles[mb_strtolower(trim($match["title"]))];
            $duration = 0;

            if (isset($seen[$title])) {
                continue;
            }

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
            if (strpos($end_time, ':') === false) {
                $end_time = date('d.m.Y', strtotime('+1 day', strtotime($end_time)));
            }
            $duration += strtotime($end_time) - strtotime($start_time);

            if ($duration < -6 * $MONTH) {
                $duration += $YEAR;
            }
            if (isset($match['duration'])) {
                $duration = $match['duration'];
            } else {
                $end_time = null;
                $duration /= 60;
            }

            $standings_url = null;

            foreach ($standings as $ind => $s) {
                $date = strtotime($s['date']);
                $end = strtotime($end_time);
                if ($title != $long_title && $date < $end) {
                    continue;
                }
                if (($title == $short_title) != ($s['type'] == 'short')) {
                    continue;
                }
                if (($title == $final_title) != ($s['type'] == 'final')) {
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
                "end_time" => $end_time,
                "duration" => $duration,
                "title" => $title . ". " . $main_title,
                "url" => $url,
                "standings_url" => $standings_url,
                "host" => $HOST,
                "key" => $season . ". " . $title,
                "rid" => $RID,
                "timezone" => $TIMEZONE,
            );
            $seen[$title] = true;
        }
    }

    $url = 'https://inf-open.ru/';
    $main_page = curlexec($url);
    if (preg_match('#<h1[^>]*>(?P<title>[^<]*)</h1>#s', $main_page, $match)) {
        $main_title = html_entity_decode($match['title']);

        $url = 'https://inf-open.ru/schedule/';
        $schedule_page = curlexec($url);
        $schedule_page = $replace_months($schedule_page);

        preg_match_all('#<h4[^>]*id="[^"]*"[^>]*>(?P<title>[^<]*)</h4>.*?<strong>(?P<date>[^<]*[0-9]{4})\sгода</strong>#s', $schedule_page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $title = html_entity_decode($match['title']);
            if (!preg_match_all('#[.0-9]+#', $match['date'], $dates)) {
                continue;
            }
            if (count($dates[0]) != 2) {
                continue;
            }
            list($start_time, $end_time) = $dates[0];
            $start_parts = explode('.', $start_time);
            $end_parts = explode('.', $end_time);
            if (count($start_parts) < count($end_parts)) {
                for ($i = count($start_parts); $i < count($end_parts); ++$i) {
                    $start_parts[] = $end_parts[$i];
                }
                $start_time = implode('.', $start_parts);
            }

            $year = date('Y', strtotime($end_time));
            $month = date('m', strtotime($end_time));
            if ($month < 9) {
                $year--;
            }
            $season = $year . '-' . ($year + 1);

            $contests[] = array(
                "start_time" => $start_time,
                "end_time" => $end_time,
                "title" => $title . '. ' . $main_title,
                "url" => $url,
                "host" => $HOST,
                "key" => $season . '. ' . $title,
                "rid" => $RID,
                "timezone" => $TIMEZONE,
            );
        }
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
