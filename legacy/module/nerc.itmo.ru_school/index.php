<?php

require_once dirname(__FILE__) . "/../../config.php";

$amonths = array("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря");
$replace_pairs = array();
foreach ($amonths as $ind => $month) {
    $ind = sprintf("%02d", $ind + 1);
    $replace_pairs[" $month "] = ".$ind.";
    $replace_pairs[" $month"] = ".$ind." . date('Y');
}
$replace_pairs[" феврадя "] = ".02.";

function replace_months($page, $with_year)
{
    global $replace_pairs;
    if (!$with_year) {
        $replaces = array();
        foreach ($replace_pairs as $k => $v) {
            if ($k[-1] != " ") {
                continue;
            }
            $replaces[$k] = $v;
        }
    } else {
        $replaces = $replace_pairs;
    }
    return strtr($page, $replaces);
}

$_contests = [];
$_timings = [];
$parse_full_list = isset($_GET['parse_full_list']);

// ВКОШП
$page = curlexec($URL);
if (preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*ВКОШП\s*</a>#', $page, $match)) {
    $url = $match['url'];
    $page = curlexec($url);

    preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Текущие\s*результаты\s*</a>#', $page, $matches, PREG_SET_ORDER);
    $standings_url = null;
    foreach ($matches as $match) {
        $current_standings_url = url_merge($url, $match['url']);
        if (preg_match('#internet#i', $current_standings_url)) {
            continue;
        }
        $standings_url = $current_standings_url;
        break;
    }

    if (
        preg_match('#<h2[^>]*>(?P<title>[^<]*ВКОШП\s*)</h2>#', $page, $title_match) &&
        preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Расписание\s*</a>#', $page, $schedule_match)
    ) {
        $title = $title_match['title'];
        $title = html_entity_decode($title);
        $title = htmlspecialchars_decode($title);
        $title = preg_replace('#\s+#', ' ', trim($title));
        $title = preg_replace('#ВКОШП\s*#', 'всероссийская командная олимпиада школьников по программированию', $title);

        $schedule_url = $schedule_match['url'];
        $schedule_page = curlexec($schedule_url);
        $schedule_page = replace_months($schedule_page, false);
        preg_match_all('#<td[^>]*class="(?P<class>[^"]*)"[^>]*>(?P<value>[^<]*)</td>#', $schedule_page, $matches, PREG_SET_ORDER);
        foreach ($matches as $_ => $td_match) {
            $match_value = trim($td_match['value']);
            if ($td_match['class'] == 'day') {
                if (preg_match('#[0-9]+\.[0-9]+\.[0-9]{4}#', $match_value, $date_match)) {
                    $match_date = $date_match[0];
                }
            } elseif ($td_match['class'] == 'event') {
                if (preg_match('#^[-0-9:]+$#', $match_value, $time_match)) {
                    $match_time = $time_match[0];
                } else if ($match_value == "Основной тур") {
                    $season = season_year(strtotime($match_date));
                    list($start_time, $end_time) = explode('-', $match_time);
                    $start_time = $match_date . ' ' . $start_time;
                    $end_time = $match_date . ' ' . $end_time;
                    $key = $season . "-" . ($season + 1) . "-vkoshp";
                    $_contests[$key] = array(
                        'start_time' => $start_time,
                        'end_time' => $end_time,
                        'ignore_times_after_start' => true,
                        'title' => $title,
                        'url' => $url,
                        'standings_url' => $standings_url ?? IGNOREVALUE,
                        'key' => $key,
                        'info' => ['series' => 'vkoshp'],
                    );
                    break;
                }
            }
        }
    }

    $urls = [];
    $page = replace_months($page, false);
    if (preg_match('#(?P<date>[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}).*<a[^>]*href="(?P<url>[^"]*/archive/[^"]*)"[^>]*>\s*Окончательные\s*результаты\s*</a>#s', $page, $match)) {
        $urls[] = array('base_url' => $url, 'url' => $match['url'], 'date' => $match['date']);
    }
    if (preg_match('#<a[^>]*menuleft[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Архив\s*олимпиад\s*</a>#', $page, $match)) {
        $url = $match['url'];
        $page = curlexec($url);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*/archive/[^"]*)"[^>]*>\s*Результаты\s*</a>#', $page, $url_matches, PREG_SET_ORDER);
        $page = replace_months($page, false);
        preg_match_all('#<h[^>]*>\s*Информация\s*</h[^>]*>[^/]*?(?P<date>[0-9]{1,2}\.[0-9]{1,2}.[0-9]{4})#', $page, $date_matches, PREG_SET_ORDER);
        if (count($url_matches) == count($date_matches)) {
            foreach ($url_matches as $i => $url_match) {
                $date_match = $date_matches[$i];
                $urls[] = array('base_url' => $url, 'url' => $url_match['url'], 'date' => $date_match['date']);
            }
        } else {
            trigger_error('No matching number urls and dates', E_USER_WARNING);
        }
    }

    $seen = array();

    foreach ($urls as $index => $data) {
        if ($index > 1 && !$parse_full_list) {
            break;
        }
        $url = $data['base_url'];
        $standings_url = url_merge($url, $data['url']);
        $date = $data['date'];
        $page = curlexec($standings_url);
        if (isset($seen[$standings_url])) {
            continue;
        }
        $seen[$standings_url] = true;
        if (!preg_match('#/archive/(?P<season>[0-9]{4}-[0-9]{4})/#', $standings_url, $match)) {
            trigger_error('No found season', E_USER_WARNING);
            continue;
        }
        $season = $match['season'];
        $page = preg_replace('#<br/?>#', ' ', $page);
        if (!preg_match('#<h[0-9][^>]*>(?P<title>[^<]*)<#', $page, $match)) {
            trigger_error('No found title', E_USER_WARNING);
            continue;
        }
        $title = $match['title'];
        $title = html_entity_decode($title);
        $title = htmlspecialchars_decode($title);
        $title = preg_replace('#\s+#', ' ', trim($title));

        $key = "{$season}-vkoshp";

        $_contests[$key] = array(
            'start_time' => $date,
            'duration' => '05:00',
            'ignore_times_after_start' => true,
            'title' => $title,
            'url' => $url,
            'standings_url' => $standings_url,
            'key' => $key,
            'info' => ['series' => 'vkoshp'],
        );
    }
}

// Интернет-олимпиады
$page = curlexec($URL);
preg_match_all('#<a[^>]*href="(?P<url>[^"]*/archive/(?P<key>20[0-9]{6})/[^"]*)"[^>]*>\s*Результаты\s*олимпиады\s*</a>#', $page, $matches, PREG_SET_ORDER);
$standings_urls = array();
foreach ($matches as $match) {
    $key = $match['key'];
    $url = $match['url'];
    $standings_urls[$key] = url_merge($URL, $url);
}
preg_match_all('#<td class="date">(?<date>\d+\s[^\s]+(?:\s\d+)?)[^<]*</td><td class="time">(?<date_start_time>[^\s<]*)[^<]*</td><td[^>]*>(?<durations>[^<]*)</td><td[^>]*>(?<title>[^<]*)</td>\s*</tr>#', $page, $matches, PREG_SET_ORDER);
foreach ($matches as $match) {
    $title = 'Интернет-олимпиада';
    if (empty($match['title'])) {
        $title .= ' (' . $match['title'] . ')';
    }
    $match['date'] = replace_months($match['date'], true);
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

    $contest = array(
        'start_time' => trim($match['date']) . ' ' . trim($match['date_start_time']),
        'duration' => '05:00',
        'title' => $title,
        'url' => $URL,
        'key' => $key,
    );
    $_timings[$key] = array(
        'start_time' => trim($match['date']) . ' ' . trim($match['date_start_time']),
        'duration' => '05:00',
    );

    if (isset($standings_urls[$key])) {
        $standings_url = $standings_urls[$key];
        $page = curlexec($standings_url);
        if (preg_match('#<h[0-9][^>]*>(?P<title>[^<]*)<#', $page, $match)) {
            $title = $match['title'];
            $title = html_entity_decode($title);
            $title = htmlspecialchars_decode($title);
            $title = preg_replace('#\s+#', ' ', trim($title));
            $contest['title'] = $title;
        }
        $contest['standings_url'] = $standings_url;
    }
    $_contests[$key] = $contest;
}

preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]{4}-[0-9]{4}</a>#', $page, $matches);
foreach ($matches['url'] as $url) {
    $url = url_merge($URL, $url);
    $page = curlexec($url);
    preg_match_all('#<h2>(?P<title>[^>]*)</h2>[^<]*(?:<[^>/]*>[^<]*)*<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Результаты#', $page, $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        $u = url_merge($url, $match['url']);
        if (!preg_match('#[-/](?P<key>20[0-9]{6})[-/]#', $u, $m)) {
            trigger_error("Not found key in $u", E_USER_WARNING);
            continue;
        }
        $key = $m['key'];

        $title = $match['title'];
        list($date, $title) =  preg_split('#[.,] #', $title, 2);
        $date = explode(' ', replace_months($date, true))[0];
        $title = html_entity_decode($title);

        if (isset($_contests[$key]) && isset($_contests[$key]['standings_url'])) {
            preg_match('#-(?P<subkey>[^-]*)\.[^.-]*$#', $_contests[$key]['standings_url'], $m);
            $new_key = $key . '-' . $m['subkey'];
            $_contests[$new_key] = $_contests[$key];
            $_contests[$new_key]['key'] = $new_key;
        }

        $_contests[$key] = array(
            'start_time' => isset($_timings[$key]) ? $_timings[$key]['start_time'] : $date,
            'duration' => isset($_timings[$key]) ? $_timings[$key]['duration'] : '05:00',
            'title' => $title,
            'url' => $url,
            'standings_url' => $u,
            'key' => $key,
            'skip_check_time' => true,
        );
    }
    if (!$parse_full_list) {
        break;
    }
}

foreach ($_contests as $contest) {
    $contest['host'] = $contest['host'] ?? $HOST;
    $contest['timezone'] = $contest['timezone'] ?? $TIMEZONE;
    $contest['rid'] = $contest['rid'] ?? $RID;
    $contests[] = $contest;
}
unset($_contests);

if ($RID == -1) {
    print_r($contests);
}
