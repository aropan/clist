<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page_url = $URL;

    $set_urls = array();
    $set_urls[$page_url] = true;

    for (;;) {
        $page = curlexec($page_url);

        preg_match_all('#
            <a[^>]*href="(?<url>[^"]+/contests/(?P<key>[a-z0-9]+))">(?<title>[^<]+)
            <span[^>]*>[^<]*<i[^>]*>[^<]*</i>[^<]*</span>[^<]*</a>[^<]*
            <div[^>]*class="eo-competition-row__dates">[^<]*
            (?:
                <div>(?<start_time>[^<]+)</div>[^<]*<div>(?<end_time>[^<]+)</div>[^<]*|
                <div><b>(?<date>[^<]+)</b></div><div>(?<date_start_time>[^\-]+)-(?<date_end_time>[^<]+)</div>
            )
            #xs',
            $page,
            $matches,
            PREG_SET_ORDER
        );

        $parsed_url = parse_url($page_url);
        if (isset($parsed_url['query'])) {
            unset($parsed_url['query']);
        }

        foreach ($matches as $match)
        {
            $url = url_merge($parsed_url, $match['url']);

            $contests[] = array(
                'start_time' => isset($match['date'])? $match['date'] . ' ' . trim($match['date_start_time']) : trim($match['start_time']),
                'end_time' => isset($match['date'])? $match['date'] . ' ' . trim($match['date_end_time']) : trim($match['end_time']),
                'title' => trim($match['title']),
                'url' => $url,
                'rid' => $RID,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'key' => $match['key']
            );
        }

        if (!isset($_GET['parse_full_list'])) {
            break;
        }

        preg_match_all('#<li>\s*<a[^>]*href="(?<href>[^"]+)"[^>]*>\d+</a>\s*</li>#', $page, $urls, PREG_SET_ORDER);
        $page_url = false;
        foreach ($urls as $match) {
            $url = url_merge($parsed_url, $match['href']);
            if (!isset($set_urls[$url])) {
                $set_urls[$url] = true;
                $page_url = $url;
                break;
            }
        }

        if ($page_url === false) {
            break;
        }
    }
?>
