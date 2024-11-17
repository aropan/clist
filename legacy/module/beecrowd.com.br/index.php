<?php
    require_once dirname(__FILE__) . '/../../config.php';
    $url_scheme_host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);

    $user_agent_file = dirname(__FILE__) . "/../../logs/beecrowd.user_agent";
    $cookie_file = dirname(__FILE__) . "/../../logs/beecrowd.cookie";
    $header = array();
    if (file_exists($user_agent_file)) {
        $user_agent = trim(file_get_contents($user_agent_file));
        $header[] = "User-Agent: $user_agent";
    }
    $curlexec_params = ['http_header' => $header, 'with_curl' => true, 'cookie_file' => $cookie_file];

    for ($n_page = 1;; $n_page += 1) {
        $url = $url_scheme_host . "/en/contests?page=$n_page";
        $page = curlexec($url, null, $curlexec_params);

        if (strpos($url, '/login') !== false) {
            preg_match_all('#<input[^>]*name="(?P<name>[^"]*)"(?:[^>]*value="(?P<value>[^"]*)")?[^>]*>#', $page, $matches, PREG_SET_ORDER);
            $fields = array();
            foreach ($matches as $match) {
                $fields[$match['name']] = isset($match['value'])? $match['value'] : '';
            }
            require_once dirname(__FILE__) . '/secret.php';
            $fields['email'] = $BEECROWD_EMAIL;
            $fields['password'] = $BEECROWD_PASSWORD;
            $page = curlexec($url, $fields, $curlexec_params);
        }

        preg_match_all('#
            <tr[^>]*>\s*
                <td[^>]*>\s*<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*(?P<key>[0-9]+)\s*</a>\s*</td>\s*
                <td[^>]*>(?:\s*<[^/][^>]*>)*\s*</td>\s*
                <td[^>]*>(?:\s*<[^/][^>]*>)*\s*</td>\s*
                <td[^>]*>\s*(?:<[^/][^>]*>\s*)*<a[^>]*>(?P<title>[^<]*)</a>\s*(?:<[^>]*>\s*)*</td>\s*
                <td[^>]*class="[^"]*date[^"]*"[^>]*>(?P<start>[^<]*)</td>\s*
                <td[^>]*>(?P<duration>[^<]*)</td>\s*
            </tr>#x',
            $page,
            $matches,
            PREG_SET_ORDER,
        );

        $nothing = true;
        foreach ($matches as $c) {
            foreach ($c as $k => $v) {
                $c[$k] = trim($v);
            }
            $url = url_merge($URL, $c['url']);
            $title = $c['title'];
            if (substr($title, -3) == '...') {
                $page = curlexec($url, null, $curlexec_params);
                if (preg_match('#</h2>\s*<p[^>]*>(?P<title>[^<]*)</p>#', $page, $match)) {
                    $title = $match['title'];
                }
            }
            $invisible = preg_match('#<img[^>]*src="[^"]*lock.png#', $c[0])? 'true' : 'false';
            $contests[] = array(
                'start_time' => $c['start'],
                'duration' => $c['duration'],
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $c['key'],
                'invisible' => $invisible,
            );
            $nothing = false;
        }

        if (!isset($_GET['parse_full_list']) || $nothing) {
            break;
        }
    }
?>
