<?php
  require_once dirname(__FILE__) . "/../../config.php";

  $data = null;
  for ($page = 1; $page == 1 || isset($data['totalPages']) && $page <= $data['totalPages']; ++$page) {
    $url = "$URL/api/contests?page=$page&limit=10&sortBy=startTime&sortOrder=desc";
    $data = curlexec($url, null, ['json_output' => true]);
    if (!is_array($data) || !is_array($data['data'])) {
      trigger_error("Unexpected data", E_USER_WARNING);
      break;
    }
    foreach ($data['data'] as $c) {
      $url = url_merge($HOST_URL, "/contest/{$c['slug']}?contestId={$c['_id']}");
      $contests[] = array(
        'start_time' => $c['startTime'],
        'end_time' => $c['endTime'],
        'title' => $c['contestName'],
        'url' => $url,
        'rid' => $RID,
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'key' => $c['_id'],
        'info' => ['parse' => $c],
      );
    }
    if (!isset($_GET['parse_full_list'])) {
      break;
    }
  }
?>
