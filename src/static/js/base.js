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

function toggle_tooltip_object(object) {
  if (typeof object === 'string') {
    $('body').tooltip({selector: object, container: 'body', trigger: 'hover'})
  } else {
    object.removeAttr('data-toggle').tooltip({container: 'body', trigger: 'hover'})
  }
}

function toggle_tooltip() {
  toggle_tooltip_object('[data-toggle="tooltip"]')
}

$(toggle_tooltip)

function clear_tooltip() {
  $('.tooltip').tooltip('hide')
}

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

$(function() {
  $('.sortable-column').each(function() {
    var url = new URL(window.location.href)
    var sort_column = url.searchParams.get('sort_column')
    var sort_order = url.searchParams.get('sort_order')
    var column = this.getAttribute('data-column')
    url.searchParams.set('sort_column', '')
    var disable_url = url.href
    url.searchParams.set('sort_column', column)
    url.searchParams.set('sort_order', 'asc')
    var asc_url = url.href
    url.searchParams.set('sort_order', 'desc')
    var desc_url = url.href

    if (sort_column == column) {
      var order = sort_order == 'asc'? 'up' : 'down'
      $(this).append(`<a href="` + disable_url + `"><i class="sortable-column-order fas fa-chevron-` + order + `"></i></a>`)
    }

    if (sort_column != column || sort_order != 'desc') {
      $(this).append(`<a href="` + desc_url + `" class="hiding text-muted"><i class="fas fa-chevron-down"></i></a>`)
    }
    if (sort_column != column || sort_order != 'asc') {
      $(this).append(`<a href="` + asc_url + `" class="hiding text-muted"><i class="fas fa-chevron-up"></i></a>`)
    }
  })

  $('.chart-column').each(function() {
    var url = new URL(window.location.href)
    var field = this.getAttribute('data-field')
    url.searchParams.set('chart_column', field)
    $(this).append(`<a href="` + url.href + `" class="hiding text-muted"><i class="far fa-chart-bar"></i></a>`)
  })
})

function inline_button() {
  $('.reset-timing-statistic').removeClass('reset-timing-statistic').click(function(e) {
    e.preventDefault()
    var btn = $(this)
    $.post('/standings/action/', {action: 'reset_contest_statistic_timing', cid: btn.attr('data-contest-id')}).done(function(data) {
      btn.attr('data-original-title', data.message).tooltip('show')
    })
  })

  $('.database-href').removeClass('database-href').click(function(e) {
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

$.browser = {};
(function () {
  $.browser.msie = false;
  $.browser.version = 0;
  if (navigator.userAgent.match(/MSIE ([0-9]+)\./)) {
    $.browser.msie = true;
    $.browser.version = RegExp.$1;
  }
  $.browser.firefox = navigator.userAgent.search("Firefox") > -1;
})();


function log_ajax_error(response, element = null) {
  var message;
  if (typeof response.responseJSON !== 'undefined') {
    if (response.responseJSON.redirect) {
      window.location.replace(response.responseJSON.redirect)
    } else {
      message = response.responseJSON.message
    }
  } else {
    if (response.responseText.length < 100) {
      message = "{status} {statusText}: {responseText}".format(response)
    } else {
      message = "{status} {statusText}, more in console".format(response)
      console.log(response.responseText)
    }
  }
  if (element) {
    element.text(message)
    element.removeClass('hidden')
  } else {
    $.notify(message, 'error')
  }
}


;!(function ($) {
  $.fn.classes = function (callback) {
    var classes = [];
    $.each(this, function (i, v) {
      var splitClassName = (v.className || "").split(/\s+/);
      var cs = []
      for (var j = 0; j < splitClassName.length; j++) {
        var className = splitClassName[j];
        cs.push(className);
        if (classes.indexOf(className) === -1) {
          classes.push(className);
        }
      }
      if ('function' === typeof callback) {
        for (var i in cs) {
          callback(cs[i], v);
        }
      }
    });
    return classes;
  };
})(jQuery);


$.fn.findWithSelf = function(selector) {
  var result = this.find(selector)
  this.each(function() {
    if ($(this).is(selector)) {
      result = result.add($(this))
    }
  });
  return result
}


function shuffle(array) {
  let currentIndex = array.length
  let randomIndex

  while (currentIndex != 0) {
    randomIndex = Math.floor(Math.random() * currentIndex)
    currentIndex--
    [array[currentIndex], array[randomIndex]] = [array[randomIndex], array[currentIndex]]
  }
  return array
}

function copyTextToClipboard(text) {
  var $temp = $('<input>')
  $('body').append($temp)
  $temp.val(text).select()
  document.execCommand('copy')
  $temp.remove()
}

$(function() {
  $('.copy-to-clipboard').click(function() {
    var el= $(this)
    copyTextToClipboard(el.text())
    el.attr('title', 'copied')
    el.tooltip('show')
    $.notify('Copied to clipboard', 'success')
    setTimeout(function() { el.attr('title', ''); el.tooltip('destroy'); }, 1000)
  })
})

function select2_ajax_conf(query, field, addition_params) {
  return {
    url: '/settings/search/',
    dataType: 'json',
    delay: 314,
    data: function (params) {
      var ret = {
        query: query,
        page: params.page || 1
      }
      ret[field] = params.term
      if (addition_params !== undefined) {
        for (var key in addition_params) {
          ret[key] = addition_params[key].val()
        }
      }
      return ret
    },
    processResults: function (data, params) {
      return {
        results: data.items,
        pagination: {
          more: data.more
        }
      }
    },
    cache: true,
  }
}

// Resizer
$(function() {
  // Query the element
  const resizer = document.getElementById('drag_me');
  const leftSide = resizer? resizer.previousElementSibling : null;
  const rightSide = resizer? resizer.nextElementSibling : null;

  // The current position of mouse
  let drag_me_x = 0;
  let drag_me_y = 0;
  let drag_me_left_width = 0;

  // Handle the mousedown event
  // that's triggered when user drags the resizer
  const mouseDownHandler = function (e) {
    // Get the current mouse position
    drag_me_x = e.clientX;
    drag_me_y = e.clientY;
    drag_me_left_width = leftSide.getBoundingClientRect().width;

    // Attach the listeners to `document`
    document.addEventListener('mousemove', mouseMoveHandler);
    document.addEventListener('mouseup', mouseUpHandler);
  };

  const mouseMoveHandler = function (e) {
    // How far the mouse has been moved
    const dx = e.clientX - drag_me_x;
    const dy = e.clientY - drag_me_y;

    const newLeftWidth = ((drag_me_left_width + dx) * 100) / resizer.parentNode.getBoundingClientRect().width;
    leftSide.style.width = `${newLeftWidth}%`;

    resizer.style.cursor = 'col-resize';
    document.body.style.cursor = 'col-resize';

    leftSide.style.userSelect = 'none';
    leftSide.style.pointerEvents = 'none';

    rightSide.style.userSelect = 'none';
    rightSide.style.pointerEvents = 'none';
  };

  const mouseUpHandler = function () {
    resizer.style.removeProperty('cursor');
    document.body.style.removeProperty('cursor');

    leftSide.style.removeProperty('user-select');
    leftSide.style.removeProperty('pointer-events');

    rightSide.style.removeProperty('user-select');
    rightSide.style.removeProperty('pointer-events');

    // Remove the handlers of `mousemove` and `mouseup`
    document.removeEventListener('mousemove', mouseMoveHandler);
    document.removeEventListener('mouseup', mouseUpHandler);
  };

  // Attach the handler
  if (resizer) {
    resizer.addEventListener('mousedown', mouseDownHandler);
  }
})


$(function() {
  $('body').keyup(function(event) {
    if ($(event.target).is('input')) {
      event.preventDefault()
    }
  })
})

function replace_tag(element, originalTag, replacementTag) {
  var newElement = element.prop('outerHTML')
  newElement = newElement.replace(new RegExp('<' + originalTag, 'ig'), '<' + replacementTag)
  newElement = newElement.replace(new RegExp('</' + originalTag, 'ig'), '</' + replacementTag)
  newElement = $(newElement)
  element.replaceWith(newElement)
  return newElement
}

function toggle_hidden(element, event) {
  var cls = $(element).attr('data-class')
  $('.' + cls).toggleClass('hidden')
  if (event !== undefined) {
    event.preventDefault()
    event.stopImmediatePropagation()
  }
}

$(function() {
  $('.database-link').each((_, e) => {
    var between = 10
    var offset = between
    $(e).prevAll('.database-link').each((_, e) => { offset += $(e).width() + between })
    $(e).css('margin-left', offset)
  })
})

function update_urls_params(params) {
  var url = new URL(window.location.href)
  for (var k in params) {
    v = params[k]
    if (v == undefined) {
      url.searchParams.delete(k)
    } else {
      url.searchParams.set(k, v)
    }
  }
  window.history.replaceState(null, null, url)
}

function click_activity(event, el, callback) {
  event.preventDefault()
  var loading_spinner = null
  var loading_timeout_id = setTimeout(function() {
    loading_spinner = $('<i class="fas fa-circle-notch fa-spin"></i>')
    $(el).after(loading_spinner)
    $(el).hide()
  }, 500)
  $.ajax({
    type: 'POST',
    url: change_url,
    data: {
        pk: coder_pk,
        name: 'activity',
        content_type: $(el).attr('data-content-type'),
        object_id: $(el).attr('data-object-id'),
        activity_type: $(el).attr('data-activity-type'),
        value: !$(el).hasClass('selected-activity'),
    },
    success: function(data, _, xhr) {
      if (data['status'] == 'ok') {
        var selector = ''
        selector += '[data-content-type="' + $(el).attr('data-content-type') + '"]'
        selector += '[data-object-id="' + $(el).attr('data-object-id') + '"]'
        selector += '[data-activity-type="' + $(el).attr('data-activity-type') + '"]'
        $(selector).each(function() {
          if (data['state']) {
            $(this).removeClass($(this).data('unselected-class'))
            $(this).addClass($(this).data('selected-class'))
            $(this).addClass('selected-activity')
          } else {
            $(this).removeClass($(this).data('selected-class'))
            $(this).addClass($(this).data('unselected-class'))
            $(this).removeClass('selected-activity')
          }
        })
        if (callback) {
          callback(el)
        }
      } else {
        log_ajax_error(xhr)
      }
    },
    error: log_ajax_error,
    complete: function(data) {
      clearTimeout(loading_timeout_id)
      if (loading_spinner) {
        loading_spinner.remove()
        $(el).show()
      }
    },
  })
  return false
}
