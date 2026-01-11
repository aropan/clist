<?php

require_once dirname(__FILE__) . "/../../config.php";

$main_page = curlexec($URL);
$_contests = array();

function parse_contest_title($page)
{
    if (!preg_match('#<h2[^>]*>(?P<title>[^<]*)</h2>#', $page, $m) || empty($m['title'])) {
        return [null, null];
    }
    $title = $m['title'];
    $title = html_entity_decode($title);
    $title = htmlspecialchars_decode($title);
    $key = slugify($title);
    return [$title, $key];
}

function parse_nef()
{
    global $main_page, $URL, $_contests;


    preg_match('#<a[^>]*href="(?P<url>[^">]*)"[^>]*>\s*ne\s*finals\s*</a>#si', $main_page, $match);
    $url = url_merge($URL, $match['url']);

    if (isset($_GET['parse_full_list'])) {
        $page = curlexec($url);
        $urls = [];
        preg_match_all('#<a[^>]*href="(?P<url>[^">]*)"[^>]*>\s*[0-9]{4}\s*</a>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $urls[] = url_merge($URL, $match['url']);
        }
    } else {
        $urls = [$url];
    }

    foreach ($urls as $url) {
        $page = curlexec($url);
        preg_match('#(?P<year>[0-9]{4})#', $url, $match);
        $year = $match['year'];

        $standings_url = null;
        if (preg_match('#<a[^>]*href="(?P<url>[^"]*archive[^"]*standings[^"]*)"[^>]*>\s*standings\s*</a>#i', $page, $standings_match)) {
            $standings_url = url_merge($URL, $standings_match['url']);
        }

        preg_match_all("#<h3[^>]*\bid\b[^>]*>(?P<date>[^<]*)</h3>\s*<table[^>]*>.*?</table>#s", $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $_ => $day) {
            if (preg_match('#<td[^>]*class="time"[^>]*>(?P<time>[^<]*)</td>\s*<td[^>]*class="name"[^>]*>[^a-zA-Z]*(?:Northern Eurasia Finals|Contest)[^a-zA-Z]*</td>#', $day[0], $match)) {
                list($start_time, $end_time) = explode("-", $match['time']);
                $start_time = $day['date'] . ' ' . $start_time . ' ' . $year;
                $end_time = $day['date'] . ' ' . $end_time . ' ' . $year;

                $title = "NERC, Northern Eurasia Finals";
                $key = "icpc-" . $year . "-" . ($year + 1) . "-" . slugify($title);
                $old_key = IGNOREVALUE;

                if ($standings_url) {
                    $standings_page = curlexec($standings_url);
                    list($standings_title, $standings_key) = parse_contest_title($standings_page);
                    if ($standings_title) {
                        $old_key = $key;
                        $title = $standings_title;
                        $key = $standings_key;
                    }
                }

                $_contests[] = array(
                    'start_time' => $start_time,
                    'end_time' => $end_time,
                    'ignore_times_after_start' => true,
                    'title' => $title,
                    'url' => $url,
                    'standings_url' => $standings_url ?? IGNOREVALUE,
                    'key' => $key,
                    'old_key' => $old_key,
                    'info' => ['series' => 'nef'],
                );
                break;
            }
        }
    }
}

function parse_archive()
{
    global $main_page, $URL, $_contests;

    if (!preg_match('#<div[^>]*class="[^"]*\bmenuleft\b[^"]*"[^>]*>.*?</div>#s', $main_page, $match)) {
        return;
    }

    $urls = array();
    preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]+</a>#', $match[0], $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        $urls[] = url_merge($URL, $match['url']);
        if (!isset($_GET['parse_full_list'])) {
            break;
        }
    }

    $standings_url_keys = array();
    foreach ($_contests as $contest) {
        if ($contest['standings_url'] !== IGNOREVALUE) {
            $standings_url_keys[$contest['standings_url']] = $contest['key'];
        }
    }

    foreach ($urls as $url) {
        $page = curlexec($url);
        preg_match('#(?P<year>[0-9]{4})#', $url, $match);
        $year = $match['year'];

        preg_match_all('#<a[^>]*href="(?P<url>[^"]*[0-9]+[^"]*standings[^"]*)"[^>]*>\s*Standings\s*</a>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $u = url_merge($url, $match['url']);
            $page = curlexec($u);

            list($title, $key) = parse_contest_title($page);
            if (empty($title)) {
                continue;
            }

            $old_key = isset($standings_url_keys[$u]) && $standings_url_keys[$u] !== $key ? $standings_url_keys[$u] : IGNOREVALUE;
            $ignore_times_after_start = true;

            $start_time = "$year-09-02";
            $duration = '05:00';
            $xml_url = url_merge($u, "standings.xml");
            $xml_page = curlexec($xml_url);
            if (preg_match('#<contest\s*(?P<attributes>[^>]*)>#s', $xml_page, $match)) {
                preg_match_all('#(?P<name>[^=\s]*)="(?P<value>[^"]*)"#', $match['attributes'], $attributes, PREG_SET_ORDER);
                $attributes = array_column($attributes, 'value', 'name');
                if (isset($attributes['start-time-millis'])) {
                    $new_start_time = round($attributes['start-time-millis'] / 1000);
                    if (date('Y', $new_start_time) === $year) {
                        $start_time = $new_start_time;
                        $ignore_times_after_start = false;
                    }
                }
                if (isset($attributes['length'])) {
                    $duration = round($attributes['length'] / 1000 / 60);
                }
            }

            $_contests[] = array(
                'start_time' => $start_time,
                'duration' => $duration,
                'skip_check_time' => true,
                'ignore_times_after_start' => $ignore_times_after_start,
                'title' => $title,
                'url' => $u,
                'standings_url' => $u,
                'key' => $key,
                'old_key' => $old_key,
            );
        }
    }
}

parse_nef();
parse_archive();

foreach ($_contests as $contest) {
    $contest['rid'] = $RID;
    $contest['host'] = $HOST;
    $contest['timezone'] = $TIMEZONE;
    $contests[] = $contest;
}

unset($_contests);
