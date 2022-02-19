<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $urls = array($URL);
    if (isset($_GET['parse_full_list'])) {
        $url_scheme_host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);
        $urls[] = $url_scheme_host . '/past-contests?user_created=off';
    }
    foreach ($urls as $url) {
        $page = curlexec($url);
        list($clean_url) = explode('?', $url);
        foreach (
            array(
                'Ongoing' => 'start_time',
                'Upcoming' => 'start_time',
                'Past' => 'end_time'
            ) as $t => $v
        ) {
            if (!preg_match("#<h2>$t</h2>\s*<table[^>]*>.*?</table>#s", $page, $match)) {
                continue;
            }
            preg_match_all('#
                <tr[^>]*>\s*
                    <td[^>]*>\s*
                        (?:<[^>]*>\s*)+
                        <a[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<title>[^<]*)</a>\s*
                    </td>\s*
                    (?:<td[^>]*>[0-9:\s]+</td>\s*)??
                    <td[^>]*>(?P<duration>[^<]*)</td>\s*
                    <td[^>]*>(?P<date>[^<]*)</td>\s*
                    (?:<[^>]*>\s*|<button[^>]*>[^<]*</button>)*
                </tr>
                #msx',
                $match[0],
                $matches,
                PREG_SET_ORDER
            );
            foreach ($matches as $data) {
                $key = explode('/', $data['url']);
                $key = end($key);
                $date = trim($data['date']);
                if (substr_count($date, ' ') == 1) {
                    $date = strtotime($date);
                    $day = 24 * 60 * 60;
                    if ($date + $day < time()) {
                        $date += $day;
                    }
                }
                $contests[] = array(
                    $v => $date,
                    'title' => $data['title'],
                    'duration' => preg_replace('#^([0-9]+:[0-9]+):[0-9]+$#', '$1', $data['duration']),
                    'url' => url_merge($clean_url, $data['url']),
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $key,
                );
            }
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
