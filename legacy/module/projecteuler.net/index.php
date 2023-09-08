<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36';
    curl_setopt($CID, CURLOPT_USERAGENT, $user_agent);

    $proxy_file = dirname(__FILE__) . "/../../logs/projecteuler.proxy";
    $proxy = file_exists($proxy_file)? json_decode(file_get_contents($proxy_file)) : false;
    if ($proxy) {
        echo " (proxy)";
        curl_setopt($CID, CURLOPT_PROXY, $proxy->addr . ':' . $proxy->port);
    } else {
        return;
    }

    $urls = array('https://projecteuler.net/recent');

    if (isset($_GET['parse_full_list'])) {
        $url = 'https://projecteuler.net/archives';
        $page = curlexec($url);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]+</a>#', $page, $matches);
        foreach ($matches['url'] as $u) {
            $urls[] = url_merge($url, $u);
        }
        $urls = array_unique($urls);
    }

    foreach ($urls as $url) {
        $page = curlexec($url);
        preg_match_all('#
            <tr>\s*
                <td[^>]*>(?P<key>[0-9]+)</td>\s*
                <td[^>]*>
                    <a[^>]*href="(?P<url>[^"]*)"[^>]*Published\s*on\s*(?P<start_time>[^"]*)"[^>]*>
                        (?P<name>.*?)
                    </a>\s*</td>
            #x', $page, $matches, PREG_SET_ORDER
        );

        foreach ($matches as $match) {
            $title = strip_tags("Problem ${match['key']}. ${match['name']}");
            $contests[] = array(
                'start_time' => $match['start_time'],
                'duration' => '00:00',
                'title' => $title,
                'url' => url_merge($url, $match['url']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $match['key'],
            );
        }
    }


    $url = 'https://projecteuler.net/news';
    $page = curlexec($url);
    preg_match_all('#<li[^>]*>(?:[^>]*>)?(?P<title>Problem[^0-9]*(?P<key>[0-9 ]+))[^A-Z]*(?P<start_time>[^<\)]*)#', $page, $matches, PREG_SET_ORDER);

    foreach ($matches as $match) {
        $contests[] = array(
            'start_time' => $match['start_time'],
            'duration' => '00:00',
            'title' => $match['title'],
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => trim($match['key']),
        );
    }

    $url = 'https://projecteuler.net/minimal=new';
    $page = curlexec($url);
    $lines = explode("\r\n\r\n", $page);
    $lines = end($lines);
    $lines = explode("\n", $lines);
    foreach ($lines as $line) {
        $data = explode("#", trim($line));
        if (count($data) < 3) {
            continue;
        }
        $key = trim($data[0]);
        $start_time = trim($data[2]);
        if (!is_numeric($key) || !is_numeric($start_time)) {
            continue;
        }
        $contests[] = array(
            'start_time' => $start_time,
            'duration' => '00:00',
            'title' => 'Problem ' . $key,
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key,
        );
    }


    if ($RID == -1) {
        print_r($contests);
    }

    if ($proxy) {
        curl_setopt($CID, CURLOPT_PROXY, null);
    }
    curl_setopt($CID, CURLOPT_USERAGENT, $USER_AGENT);
?>
