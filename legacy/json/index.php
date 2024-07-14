<?php
  require_once dirname(__FILE__) . "/../config.php";

  header('Content-Type: application/json; charset=utf-8');

  $time = date('Y-m-d H:i:s', time());
  $coming_contests = $db->getArray("
    select clist_resource.host, clist_contest.* from clist_contest
    inner join clist_resource on clist_resource.id = clist_contest.resource_id
    where start_time > '$time' and clist_contest.resource_id IN (1,3,6,7,12,13,24,69)
    order by start_time, title
    limit 10
  ");

  $contests = array();
  foreach ($coming_contests as $contest)
  {
    $contests[] = 
      array(
        'title' => $contest['title'],
        'url' => $contest['url'],
        'host' => $contest['host'],
        'start_time' => date('d.m.y H:i', strtotime($contest['start_time']) + 10800),
        'end_time' => date('d.m.y H:i', strtotime($contest['end_time']) + 10800),
      );
  }
  echo "var olympBlock = " . json_encode($contests) . ";";
?>
