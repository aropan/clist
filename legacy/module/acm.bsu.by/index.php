<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);

    preg_match_all('#<td[^>]*>(?P<date>[^<]*)</td>\s*<td[^>]*>\s*<a[^>]href="(?P<url>(?P<base_url>[^"]*/contests/(?P<key>[0-9]+))[^"]*)"[^>]*>(?P<title>[^<]*)</a>#', $page, $matches, PREG_SET_ORDER);

    foreach ($matches as $match) {
        $title = html_entity_decode(trim($match['title']), ENT_QUOTES | ENT_HTML5);
        $start_time = $match['date'];

        if (!isset($_GET['parse_full_list'])) {
            if (time() - strtotime($start_time) > 60 /* minutes */ * 60 /* hours */ * 24 /* days */ * 7) {
                continue;
            }
        }

        $standings_url = url_merge($URL, $match['base_url']) . '/standings/';
        $page = curlexec($standings_url);

        if (preg_match('#<div[^>]*class="ir-time">[^<]*of(?P<duration>[^<]*)</div>#', $page, $m)) {
            $duration = trim($m['duration']);
            $duration = preg_replace('#(:[0-9]+):[0-9]+#', '\\1', $duration);
        } else {
            $duration = '00:00';
        }

        $contest = array(
            'title' => $title,
            'start_time' => $start_time,
            'duration' => $duration,
            'url' => url_merge($URL, $match['url']),
            'standings_url' => $standings_url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $match['key'],
        );

        $contests[] = $contest;
    }
?>
