<?php
    function smarty_function_version($params, &$smarty)
    {
        echo $params['file'] . '?' . filemtime($_SERVER['DOCUMENT_ROOT'] . $params['file']);
    }
?>
