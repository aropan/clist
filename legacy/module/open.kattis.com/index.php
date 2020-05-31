<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);
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
        <div[^>]*>.*?</div>\s*
        <a[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<title>[^<]*)</a>\s*
    </td>\s*
    (?:<td[^>]*>[0-9:\s]+</td>\s*)??
    <td[^>]*>(?P<duration>[^<]*)</td>\s*
    <td[^>]*>(?P<date>[^<]*)</td>\s*
    (?:<td[^>]*>\s*(?:<form[^>]*>.*?</form>\s*)?</td>\s*)?
</tr>
#msx',
            $match[0],
            $matches,
            PREG_SET_ORDER
        );
        foreach ($matches as $data) {
            $parts = explode('/', $data['url']);
            $contests[] = array(
                $v => $data['date'],
                'title' => $data['title'],
                'duration' => preg_replace('#^([0-9]+:[0-9]+):[0-9]+$#', '$1', $data['duration']),
                'url' => url_merge($URL, $data['url']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => end($parts)
            );
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
