var format = function (str, col) {
    col = typeof col === 'object' ? col : Array.prototype.slice.call(arguments, 1);

    return str.replace(/\{\{|\}\}|\{(\w+)\}/g, function (m, n) {
        if (m == "{{") { return "{"; }
        if (m == "}}") { return "}"; }
        return col[n];
    });
};

String.prototype.format = function (col) {
    return format(this, col);
}

$(function(){
    if (window.location.hash != "") {
        $('a[href="' + window.location.hash + '"]').click()
    }
    var url = window.location.pathname
    $('.nav a[href="'+url+'"]').parent().addClass('active')
});


// https://github.com/gouch/to-title-case/blob/master/to-title-case.js
String.prototype.toTitleCase = function(){
    var smallWords = /^(a|an|and|as|at|but|by|en|for|if|in|nor|of|on|or|per|the|to|vs?\.?|via)$/i;

    return this.replace(/[A-Za-z0-9\u00C0-\u00FF]+[^\s-]*/g, function(match, index, title){
        if (index > 0 && index + match.length !== title.length &&
                match.search(smallWords) > -1 && title.charAt(index - 2) !== ":" &&
                (title.charAt(index + match.length) !== '-' || title.charAt(index - 1) === '-') &&
                title.charAt(index - 1).search(/[^\s-]/) < 0) {
            return match.toLowerCase();
        }

        if (match.substr(1).search(/[A-Z]|\../) > -1) {
            return match;
        }

        return match.charAt(0).toUpperCase() + match.substr(1);
    });
};

function toggle_tooltip() {
  $('[data-toggle="tooltip"]').removeAttr('data-toggle').tooltip({container: 'body', trigger: 'hover'})
}

$(toggle_tooltip)

function slugify(text) {
  return text.toString().toLowerCase()
    .replace(/\s+/g, '-')           // Replace spaces with -
    .replace(/[^\w\-]+/g, '')       // Remove all non-word chars
    .replace(/\-\-+/g, '-')         // Replace multiple - with single -
    .replace(/^-+/, '')             // Trim - from start of text
    .replace(/-+$/, '');            // Trim - from end of text
}

function get_y_chart(value, y_axis) {
  value = (y_axis.max - value) / (y_axis.max - y_axis.min)
  value = Math.min(Math.max(value, 0), 1)
  return value * (y_axis.bottom - y_axis.top) + y_axis.top
}

function get_x_chart(value, x_axis) {
  value = (value - x_axis.min) / (x_axis.max - x_axis.min)
  value = Math.min(Math.max(value, 0), 1)
  return value * (x_axis.right - x_axis.left) + x_axis.left
}


$(() => $(".table-float-head").floatThead({
  zIndex: 999,
  responsiveContainer: function($table){
      return $table.closest(".table-responsive");
  },
}))

// Fixed transparent table header
$(function() {
  $('table th').each(function() {
    var color = $(this).css('background-color')
    if (color == 'rgba(0, 0, 0, 0)') {
      $(this).parents().each(function() {
        if (color == 'rgba(0, 0, 0, 0)') {
          color = $(this).css('background-color')
        }
      })
      $(this).css('background-color', color)
    }
  })
})

function update_sticky_header_problems_top() {
  $('tr.header-problems th').css('top', $('tr.header-row:first').height())
}

$(function() {
  $('.sortable-column').each(function() {
    var url = new URL(window.location.href)
    var sort_column = url.searchParams.get('sort_column')
    var sort_order = url.searchParams.get('sort_order')
    var column = this.getAttribute('data-column')
    url.searchParams.set('sort_column', column)
    url.searchParams.set('sort_order', 'asc')
    var asc_url = url.href
    url.searchParams.set('sort_order', 'desc')
    var desc_url = url.href

    if (sort_column == column) {
      var order = sort_order == 'asc'? 'up' : 'down'
      $(this).append(`<i class="sortable-column-order fas fa-chevron-` + order + `"></i>`)
    }

    if (sort_column != column || sort_order != 'desc') {
      $(this).append(`<a href="` + desc_url + `" class="text-muted"><i class="fas fa-chevron-down"></i></a>`)
    }
    if (sort_column != column || sort_order != 'asc') {
      $(this).append(`<a href="` + asc_url + `" class="text-muted"><i class="fas fa-chevron-up"></i></a>`)
    }
  })
})

function inline_button() {
  $('.reset-timing-statistic').click(function(e) {
    e.preventDefault()
    var btn = $(this)
    $.post('/standings/action/', {action: 'reset_contest_statistic_timing', cid: btn.attr('data-contest-id')}).done(function(data) {
      btn.attr('data-original-title', data.message).tooltip('show')
    })
  })

  $('.database-href').click(function(e) {
    var btn = $(this)
    window.open(btn.attr('data-href'), "_blank");
    return false
  })
}

$(inline_button)


/*
 * Chartjs printable version
 * https://github.com/chartjs/Chart.js/issues/1350#issuecomment-320265946
 */

function beforePrint () {
  for (const id in Chart.instances) {
    Chart.instances[id].resize()
  }
}

if (window.matchMedia) {
  let mediaQueryList = window.matchMedia('print')
  mediaQueryList.addListener((mql) => {
    if (mql.matches) {
      beforePrint()
    }
  })
}

window.onbeforeprint = beforePrint
