<?php
    require_once dirname(__FILE__) . '/../../config.php';

    for ($n_page = 1;; $n_page += 1) {
        $url = "https://www.beecrowd.com.br/judge/en/contests?page=$n_page";
        $page = curlexec($url);

        if (strpos($url, '/login') !== false) {
            preg_match_all('#<input[^>]*name="(?P<name>[^"]*)"(?:[^>]*value="(?P<value>[^"]*)")?[^>]*>#', $page, $matches, PREG_SET_ORDER);
            $fields = array();
            foreach ($matches as $match) {
                $fields[$match['name']] = isset($match['value'])? $match['value'] : '';
            }
            require_once dirname(__FILE__) . '/secret.php';
            $fields['email'] = $BEECROWD_EMAIL;
            $fields['password'] = $BEECROWD_PASSWORD;
            $page = curlexec($url, $fields);
        }

        preg_match_all('#
            <tr[^>]*>\s*
                <td[^>]*>\s*<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*(?P<key>[0-9]+)\s*</a>\s*</td>\s*
                <td[^>]*>.*?</td>\s*
                <td[^>]*>.*?</td>\s*
                <td[^>]*>\s*<a[^>]*>(?P<title>[^<]*)</a>\s*</td>\s*
                <td[^>]*class="[^"]*date[^"]*"[^>]*>(?P<start>[^<]*)</td>\s*
                <td[^>]*>(?P<duration>[^<]*)</td>\s*
            </tr>#xs',
            $page,
            $matches,
            PREG_SET_ORDER,
        );

        $nothing = true;
        foreach ($matches as $c) {
            $url = url_merge($URL, $c['url']);
            $title = $c['title'];
            if (substr($title, -3) == '...') {
                $page = curlexec($url);
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
