<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $urls = array($URL, 'https://hackerrank.com/rest/contests/college');
    foreach ($urls as $url) {
        $json = curlexec($url, NULL, array('json_output' => true));
        foreach ($json['models'] as $model)
        {
            $contests[] = array(
                'start_time' => date('r', $model['epoch_starttime']),
                'end_time' => date('r', $model['epoch_endtime']),
                'title' => $model['name'],
                'url' => 'https://hackerrank.com/contests/' . $model['slug'],
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => 'UTC',
                'key' => $model['id']
            );
        }
    }

    $url = 'https://hackerrank.com/api/hrw/resources/competitions?filter%5Bstatus%5D=published';
    while ($url) {
        $json = curlexec($url, NULL, array('json_output' => true));
        foreach ($json['data'] as $c) {
            $attrs = $c['attributes'];
            $contests[] = array(
                'start_time' => $attrs['starts_at'],
                'end_time' => $attrs['ends_at'],
                'title' => $attrs['name'],
                'url' => 'https://hackerrank.com/competitions/' . $attrs['slug'],
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => 'UTC',
                'key' => 'competitions/' . $c['id'],
            );
        }
        if (!isset($json['links']['next'])) {
            break;
        }
        $url = $json['links']['next'];
    }


    if ($RID == -1) {
        print_r($contests);
    }
?>
