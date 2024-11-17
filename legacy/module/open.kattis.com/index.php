<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $host = parse_url($URL, PHP_URL_HOST);
    $host_parts = explode('.', $host);
    $subdomain = count($host_parts) == 3 && $host_parts[0] != 'open'? $host_parts[0] : false;

    $urls = array($URL);
    if (!$subdomain && isset($_GET['parse_full_list'])) {
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
            ) as $table_title => $date_field
        ) {
            if (!preg_match("#<h2[^>]*>$table_title</h2>([^<]*<[^/][^>]*>)*\s*<table[^>]*>.*?</table>#s", $page, $match)) {
                continue;
            }

            $table = parsed_table($match[0]);

            foreach ($table as $data) {
                $title = $data['name'];
                $title = preg_replace('/[^0-9a-z]*â[^0-9a-z]*/i', ' - ', $title);

                $url = url_merge($clean_url, $data['name:url']);
                $key = explode('/', $url);
                $key = end($key);
                if ($subdomain) {
                    $key = "$subdomain.$key";
                }

                $date = trim($data[str_replace('_', '-', $date_field)]);
                if (substr_count($date, ' ') == 1) {
                    $date = strtotime($date);
                    $day = 24 * 60 * 60;
                    if ($date + $day < time()) {
                        $date += $day;
                    } else if ($date_field == 'end_time' && $date > time()) {
                        $date -= $day;
                    }
                }

                $duration = preg_replace('#^([0-9]+:[0-9]+):[0-9]+$#', '$1', $data['length']);

                $contests[] = array(
                    $date_field => $date,
                    'title' => $title,
                    'duration' => $duration,
                    'url' => $url,
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
