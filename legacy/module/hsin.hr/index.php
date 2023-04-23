<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $debug_ = $RID == -1;

    $url = $URL;
    $page = curlexec($url);
    $urls = array($url);
    if (preg_match_all('#<a[^>]*href="(?P<url>archive/[0-9_]*/[^"]*)"[^>]*>#', $page, $matches)) {
        if (isset($_GET['parse_full_list'])) {
            $old_urls = $matches['url'];
        } else {
            $old_urls = array(end($matches['url']));
        }
        foreach ($old_urls as $url) {
            $urls[] = url_merge($URL, $url);
        }
    }

    foreach ($urls as $url) {
        $page = curlexec($url);
        if (!preg_match('#[0-9]{4}.[0-9]{4}#', $page, $match)) {
            continue;
        }
        $season = $match[0];
        $season[4] = '-';

        preg_match_all('#<td[^>]*>\s*<div[^>]*class="naslov">(?<title>[^<]+)</div>.*?<a [^>]+>(?<date>\d\d\.\d\d\.\d\d\d\d)\.<br />(?<date_start_time>\d\d:\d\d) GMT/UTC.*?</td>#si', $page, $matches, PREG_SET_ORDER);

        foreach ($matches as $m) {
            $title = $m['title'];

            $contest = array(
                'start_time' => $m['date'] . ' ' . $m['date_start_time'],
                'duration' => '03:00',
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $season . ' ' . $title,
                'skip_check_time' => true,
            );

            if (preg_match('#<a[^>]*href="(?P<href>[^"]*)"[^>]*><strong>Results</strong></a>#i', $m[0], $match)) {
                $contest['standings_url'] = url_merge($url, $match['href']);
            }

            $contests[] = $contest;
        }
    }

    if ($debug_) {
        print_r($contests);
    }
?>
