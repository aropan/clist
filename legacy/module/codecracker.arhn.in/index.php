<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $data = curlexec($URL, null, array("http_header" => array('content-type: application/json'), "json_output" => 1));

    if (!is_array($data) || isset($data['error'])) {
        trigger_error('data = ' . json_encode($data), E_USER_WARNING);
        return;
    }

    foreach ($data as $_ => $c) {
        $contests[] = array(
            'start_time' => $c['start_time'],
            'end_time' => $c['end_time'],
            'title' => $c['contest_name'],
            'url' => url_merge($HOST_URL, '/' . $c['contest_code'] . '/'),
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['contest_code'],
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
