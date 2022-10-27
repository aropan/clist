<?php
  require_once dirname(__FILE__) . '/../../config.php';

  $url = $URL;
  $data = curlexec($url, null, array("json_output" => 1));

  foreach ($data['results'] as $contest) {
    $categories = implode(' ', $contest['categories']);
    foreach ($contest['round_set'] as $round) {
      $title = $contest['name'];
      if (!empty($categories)) {
        $title .= ' [' . $categories . ']';
      }
      $title .= '. ' . $round['name'];
      $key = $round['id'];

      if ($contest['is_internal']) {
        $u = url_merge($url, "/rounds/$key", true);
      } else if (!empty($round['url'])) {
        $u = $round['url'];
      } else if (!empty($contest['url'])) {
        $u = $contest['url'];
      } else {
        $u = url_merge($url, '/contests', true);
      }

      if (strpos($u, 'russianaicup') !== false) {
        continue;
      }

      $info = $contest;
      $info['round'] = $round;
      $info = array('parse' => $info);

      $contests[] = array(
        'start_time' => $round['start_date'],
        'end_time' => $round['finish_date'],
        'title' => $title,
        'url' => $u,
        'host' => $HOST,
        'rid' => $RID,
        'timezone' => $TIMEZONE,
        'key' => $key,
        'info' => $info,
      );
    }
  }
?>
