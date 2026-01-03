<?php
require_once "helper.php";

$is_debug = true;
class db
{
    private string $host;
    private string $dbname;
    private int $port;
    private string $username;
    private string $password;
    private $link;
    private $result;

    function __construct()
    {
        $db_conf = parse_ini_file("/run/secrets/db_conf");
        $this->host = $db_conf["POSTGRES_HOST"];
        $this->dbname = $db_conf["POSTGRES_DB"];
        $this->port = $db_conf["POSTGRES_PORT"];
        $this->username = $db_conf["POSTGRES_USER"];
        $this->password = $db_conf["POSTGRES_PASSWORD"];

        $this->link = pg_connect(
            "host={$this->host} port={$this->port} user={$this->username} password={$this->password} dbname={$this->dbname} options='--client_encoding=UTF8'",
        );

        $this->link || die("Connection error");

        pg_client_encoding($this->link) == "UTF8" || die("Encoding is not UTF8");
        $this->query("SET TIME ZONE 'UTC';");
    }

    /**
     * @param string $sql
     * @param bool $ignore_error
     * @return resource|bool
     */
    function query($sql, $ignore_error = false): mixed
    {
        global $is_debug;
        $this->result = pg_query($this->link, $sql);
        if (!$this->result && $is_debug && !$ignore_error) {
            print "
                    <span style=\"color:#555555;font-size:12pt;font-family:'Arial';font-weight:bold;\">SQL query error:<br>&nbsp;&nbsp;&nbsp;Query: </span>
                    <span style=\"color:#000000;font-size:12pt;font-family:'Arial';\">" .
                $sql .
                "<br></span>
                ";
            exit(1);
        }
        return $this->result;
    }

    /**
     * @param string $sql
     * @return array|false
     */
    function getRow($sql): array|false
    {
        return pg_fetch_assoc($this->query($sql));
    }

    /**
     * @param string $sql
     * @return mixed
     */
    function getValue($sql): mixed
    {
        $arr = pg_fetch_array($this->query($sql));
        return $arr[0];
    }

    /**
     * @param string $sql
     * @return array
     */
    function getArray($sql): array
    {
        $arr = [];
        $this->result = $this->query($sql);
        while ($this->result && ($x = pg_fetch_assoc($this->result))) {
            $arr[] = $x;
        }
        return $arr;
    }

    /**
     * @param string $table
     * @param string $fields
     * @param string $where
     * @return array
     */
    function select($table, $fields = "*", $where = "1 = 1"): array
    {
        $sql = "select " . $fields . " from " . $table . " where $where";
        return $this->getArray($sql);
    }

    /**
     * @param string|null $data
     * @return string|null
     */
    function escapeString($data): ?string
    {
        if ($data === null) {
            return null;
        }
        return pg_escape_string($this->link, $data);
    }

    /**
     * @param array $a
     * @return array
     */
    function escapeArray($a): array
    {
        $res = [];
        foreach ($a as $k => $v) {
            $res[$k] = $this->escapeString($v);
        }
        return $res;
    }

    /**
     * @param string $table
     * @param string $fields
     * @param string|false $where
     * @return array|false
     */
    function getFirstRow($table, $fields, $where = false): array|false
    {
        $sql = "select " . $fields . " from " . $table . "";
        if ($where) {
            $sql .= " where " . $where;
        }
        return $this->getRow($sql);
    }

    /**
     * @param string $table
     * @param string $fields
     * @param string $values
     * @return mixed
     */
    function insert($table, $fields, $values): mixed
    {
        $sql = "insert into " . $table . "(" . $fields . ") values (" . $values . ")";
        return $this->query($sql);
    }

    /**
     * @param string $table
     * @param string|false $where
     * @param array|false $references
     * @return mixed
     */
    function delete($table, $where = false, $references = false): mixed
    {
        $sql = "delete from " . $table . "";
        if ($where) {
            $sql .= " where " . $where;
            if ($references) {
                foreach ($references as $ref_table => $ref_field) {
                    $delete_from_sql =
                        "delete from " .
                        $ref_table .
                        " where " .
                        $ref_field .
                        " in (select id from " .
                        $table .
                        " where " .
                        $where .
                        ")";
                    $sql = $delete_from_sql . "; " . $sql;
                }
            }
        }

        return $this->query($sql);
    }

    /**
     * @param string $table
     * @param string $values
     * @param string $where
     * @return mixed
     */
    function update($table, $values, $where = "1 = 1"): mixed
    {
        $sql = "update " . $table . " set " . $values . " where " . $where;
        return $this->query($sql);
    }

    /**
     * @return int
     */
    function affected_rows(): int
    {
        return pg_affected_rows($this->result);
    }

    /**
     * @return void
     */
    function close(): void
    {
        if ($this->link) {
            pg_close($this->link);
        }
    }

    function __destruct()
    {
        $this->close();
    }
}
$db = new db();
