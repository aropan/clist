<?php
    require_once dirname(__FILE__) . '/../../config.php';

    // set locale
    $url = url_merge($URL, "/locale/en");
    $seen = array();
    curlexec($url);

    for ($n_page = 1; ; $n_page += 1) {
        $page_url = "$URL?finished=$n_page";
        $page = curlexec($page_url);
        $nothing = true;

        preg_match_all('#<td>\s*<a[^>]*href="(?P<href>[^>]*olympiads/(?P<key>[0-9]+)/?)"[^>]*>(?P<title>[^<]*)</a>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $olympiads) {
            $key = $olympiads['key'];
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;

            $url = url_merge($URL, $olympiads['href']);
            $page = curlexec($url);
            if (!preg_match_all('#<tr[^>]*>\s*<th[^>]*>(?P<key>[^<]*)</th>\s*<td[^>]*>(?:\s*<[^>]*>)*\s*(?P<value>[^\s][^<]*)#', $page, $values_matches, PREG_SET_ORDER)) {
                continue;
            }

            $values = array();
            foreach ($values_matches as $match) {
                $k = trim($match['key']);
                $k = rtrim($k, ':');
                $k = strtolower($k);
                $values[$k] = trim($match['value']);
            }

            $a = explode(':', $values['duration'], -1);
            $duration = implode(':', $a);

            $start_time = preg_replace('#[^0-9.: ]#', '', $values['starts at']);
            $end_time = preg_replace('#[^0-9.: ]#', '', $values['finishes at']);

            $contests[] = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'duration' => $duration,
                'title' => htmlspecialchars_decode($olympiads['title']),
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $key,
            );
            $nothing = false;
        }

        if (!isset($_GET['parse_full_list']) || $nothing) {
            break;
        }
    }
?>
