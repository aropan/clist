<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $seen = array();
    for ($page = 1; ; $page += 1) {
        $events_url = url_merge($URL, '?p=' . $page, true);
        $events_page = curlexec($events_url);

        preg_match_all(
            '#
            <div[^>]*>\s*
            <h2>\s*<a[^>]*href="(?P<url>[^"]*/contests/(?P<key>[0-9]+)/?)"[^>]*>(?P<title>[^<]*)</a>\s*</h2>
            .*?
            </div>
            #xs',
            $events_page,
            $matches,
            PREG_SET_ORDER,
        );

        $found = false;
        foreach ($matches as $c) {
            preg_match_all('#<p>(?P<key>[^<]*)\s*:\s*(?:<span[^>]*>|<server-timestamp\s*timestamp=")?(?P<value>[^<"]*)#', $c[0], $values, PREG_SET_ORDER);
            foreach ($values as $v) {
                $c[slugify($v['key'])] = trim($v['value']);
            }
            $title = html_entity_decode($c['title']);
            $url = url_merge($events_url, $c['url']);
            $key = $c['key'];

            if (preg_match('#>\s*virtual\s*contest\s*<#i', $c[0])) {
                $title .= ' [virtual]';
            }

            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $found = true;

            $contests[] = array(
                'start_time' => $c['start-time'] / 1000,
                'duration' => $c['total-duration'],
                'duration_in_secs' => parse_duration($c['individual-duration'] ?? ''),
                'title' => $title,
                'url' => $url,
                'key' => $key,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
            );
        }

        if (!$found || empty($PARSE_FULL_LIST)) {
            break;
        }
    }
?>
