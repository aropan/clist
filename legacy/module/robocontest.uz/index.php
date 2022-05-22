<?php
    require_once dirname(__FILE__) . '/../../config.php';

    // set locale
    $url = url_merge($URL, "/locale/en");
    curlexec($url);

    for ($n_page = 1; ; $n_page += 1) {
        $page_url = "$URL?page=$n_page";
        $page = curlexec($page_url);
        $nothing = true;

        preg_match_all('#<td>\s*<a[^>]*href="(?P<href>[^>]*olympiads/(?P<key>[0-9]+)/?)"[^>]*>(?P<title>[^<]*)</a>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $olympiads) {
            $url = url_merge($URL, $olympiads['href']);
            $page = curlexec($url);
            preg_match_all('#<tr[^>]*>\s*<th[^>]*>(?P<key>[^<]*)</th>\s*<td[^>]*>(?P<value>[^<]*)</td>\s*</tr>#', $page, $matches, PREG_SET_ORDER);

            $values = array();
            foreach ($matches as $match) {
                $key = trim($match['key']);
                $key = rtrim($key, ':');
                $key = strtolower($key);
                $values[$key] = trim($match['value']);
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
                'key' => $olympiads['key'],
            );
            $nothing = false;
        }

        if (!isset($_GET['parse_full_list']) || $nothing) {
            break;
        }
    }
?>
