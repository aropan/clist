var format = function (str, col) {
  col = typeof col === 'object' ? col : Array.prototype.slice.call(arguments, 1);
  ret = str.replace(/\{\{|\}\}|\{([\w.]+)\}/g, function (m, n) {
    if (m == "{{") { return "{"; }
    if (m == "}}") { return "}"; }

    var keys = n.split(".");
    var value = col;
    for (var i = 0; i < keys.length; i++) {
      if (value[keys[i]] === undefined) return m;
      if (typeof value[keys[i]] === 'function') {
        value = value[keys[i]](value);
      } else {
        value = value[keys[i]];
      }
    }
    return value;
  });
  return ret;
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
    $.post('/standings/action/', {
      action: 'reset_contest_statistic_timing', cid: btn.attr('data-contest-id')
    }).done(function(data) {
      btn.attr('data-original-title', data.message).tooltip('show')
      notify(data.message, data.status)
    }).fail(log_ajax_error_callback)
  })

  $('.database-href').removeClass('database-href').click(function(e) {
    var btn = $(this)
    window.open(btn.attr('data-href'), "_blank");
    return false
  })
}

$(inline_button)


function confirm_action() {
  $('.confirm-action').removeClass('confirm-action').click(function(e) {
    var btn = $(this)
    if (btn.hasClass('confirmed')) {
      btn.removeClass('confirmed')
      return
    }
    e.preventDefault()
    var action = $(this).attr('data-action')
    var message = $(this).attr('data-message') || `Are you sure you want to ${(action || 'do this').toLowerCase()}?`
    var confirm_class = $(this).attr('data-confirm-class') || 'btn-primary'

    message = $('<div>').html(message)

    var pre_action = $(this).attr('data-pre-action')
    if (pre_action) {
      var action_info = $('<pre><i class="fas fa-circle-notch fa-spin"></i></pre>')
      message.append(action_info)
      var url = new URL(window.location.href)
      url.searchParams.set('action', pre_action)
      $.ajax({
        type: 'GET',
        url: url,
        success: function(response) {
          action_info.text(response.data)
        },
        error: log_ajax_error_callback,
      })
    }


    bootbox.confirm({
      size: 'small',
      message: message,
      buttons: {
        confirm: {
          label: action,
          className: confirm_class,
        },
      },
      callback: function(result) {
        if (result) {
          btn.addClass('confirmed')
          btn.click()
        }
      }
    })
  })
}

$(confirm_action)

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
      message = 'Redirecting...'
      window.location.replace(response.responseJSON.redirect)
    } else {
      message = response.responseJSON.message
    }
  } else {
    if (response.responseText && response.responseText.length < 100) {
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
    notify(message, 'error')
  }
  $('.bootbox').effect('shake')
}

function log_ajax_error_callback(response) {
  log_ajax_error(response, null)
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


function copyElementToClipboard(event, element) {
  var el = $(element)
  var text = el.data('text') || el.text()
  copyTextToClipboard(text)
  el.attr('title', 'copied')
  el.tooltip('show')
  notify('Copied "' + text + '" to clipboard', 'success')
  setTimeout(function() { el.attr('title', ''); el.tooltip('destroy'); }, 1000)
  return false
}


$(function() {
  $('.copy-to-clipboard:not([onclick])').click(function(event) { copyElementToClipboard(event, this) })
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

function click_note(event, el, callback) {
  event.preventDefault()
  var $el = $(el)
  var $note_holder = $el.closest('.note-holder')
  if ($note_holder.find('.note-div').length) {
    return
  }
  var $note_text = $note_holder.find('.note-text')

  var $note_div = $('<div class="note-div input-group">')
  $note_div.appendTo($note_holder)
  $('.note').focus()

  var $note_textarea = $('<textarea class="note-textarea form-control" rows="1" maxlength="1000">')
  $note_textarea.appendTo($note_div)
  $('<span class="note-counter text-muted small"></span>').appendTo($note_div)
  $note_textarea.on('input', note_textarea_input)
  $note_textarea.val($note_text.text())
  $note_text.hide()

  var $button_group = $('<span class="input-group-btn">')
  $button_group.appendTo($note_div)

  var $accept_note = $('<button class="btn btn-success" type="button"><i class="fas fa-check"></i></button>')
  $accept_note.appendTo($button_group)
  copy_attributes($el, $accept_note)
  $accept_note.attr('data-action', 'change')
  $accept_note.click(note_action)

  var $delete_note = $('<button class="btn btn-danger" type="button"><i class="far fa-trash-alt"></i></button>')
  $delete_note.appendTo($button_group)
  copy_attributes($el, $delete_note)
  $delete_note.attr('data-action', 'delete')
  $delete_note.click(note_action)

  $note_textarea.trigger('input')
}

function note_textarea_input() {
  var current = $(this).val().length;
  var max_length = $(this).attr("maxlength");
  var $counter = $(this).parent().find('.note-counter')
  $counter.text(`${current}/${max_length}`);
  var shift = $(this).parent().find('.input-group-btn').width()
  var margin = 5
  $counter.css('bottom', margin + 'px')
  $counter.css('right', shift + 1.5 * margin + 'px')
}

function note_action() {
  $el = $(this)

  var $i = $el.find('i')
  var loading_spinner = null
  var loading_timeout_id = setTimeout(function() {
    loading_spinner = $('<i class="fas fa-circle-notch fa-spin"></i>')
    $i.after(loading_spinner)
    $i.hide()
    $el.attr('disabled', 'disabled')
  }, 100)

  var $holder = $el.closest('.note-holder')
  var $edit = $holder.find('.note-edit')
  var $textarea = $holder.find('.note-textarea')
  var $text = $holder.find('.note-text')
  var action = $el.attr('data-action')

  $.ajax({
    type: 'POST',
    url: change_url,
    data: {
      pk: coder_pk,
      name: 'note',
      content_type: $el.attr('data-content-type'),
      object_id: $el.attr('data-object-id'),
      value: $textarea.val(),
      action: $el.attr('data-action'),
    },
    success: function(data, _, xhr) {
      if (data['status'] == 'ok') {
        var value = data['state']
        if (value) {
          $edit.addClass('selected-note')
        } else {
          $edit.removeClass('selected-note')
        }
        $text.text(value)
        $text.show()
        $el.closest('.note-div').remove()
      } else {
        log_ajax_error(xhr)
      }
    },
    error: function(response) {
      log_ajax_error(response)
    },
    complete: function(data) {
      clearTimeout(loading_timeout_id)
      if (loading_spinner) {
        loading_spinner.remove()
      }
      $i.show()
      $el.removeAttr('disabled')
    },
  })
  return false
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
        $.find(selector).forEach(function(el) {
          var $el = $(el)
          if (data['state']) {
            $el.removeClass($el.data('unselected-class'))
            $el.addClass($el.data('selected-class'))
            $el.addClass('selected-activity')
          } else {
            $el.removeClass($el.data('selected-class'))
            $el.addClass($el.data('unselected-class'))
            $el.removeClass('selected-activity')
          }
        })
        if (callback) {
          callback(el)
        }
      } else {
        log_ajax_error(xhr)
      }
    },
    error: function(response) {
      log_ajax_error(response)
    },
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

function copy_attributes(src, dst, startswith = 'data-') {
  $.each(src[0].attributes, function() {
    if (this.name.startsWith('data-')) {
      dst.attr(this.name, this.value)
    }
  })
}

$(function() {
  $('#filter-collapse').on('shown.bs.collapse', () => { $(window).trigger('resize') })
  $('#filter-collapse').on('hidden.bs.collapse', () => { $(window).trigger('resize') })
})

var delete_on_duplicate_lasts = {}

function delete_on_duplicate(with_starred = false) {
  var elements = $('[data-delete-on-duplicate]')
  var lasts = delete_on_duplicate_lasts
  var stops = {}
  elements.each(function(index) {
    if (!this.isConnected) {
      return;
    }
    var $el = $(this)
    var id = $el.attr('data-delete-on-duplicate')
    if (id in stops) {
      $el.remove()
    } else {
      if (id in lasts && !lasts[id].is($el)) {
        lasts[id].remove()
      }
      if ($el.attr('data-delete-on-duplicate-stop')) {
        stops[id] = true
      } else {
        lasts[id] = $el
      }
      if (with_starred) {
        $el.addClass('starred')
        var $show_more_el = $el.next()
        if ($show_more_el && $show_more_el.hasClass('endless_container')) {
          $el.before($show_more_el)
          $el.before($('<script/>'))
        }
      }
    }
    if (with_starred) {
      restarred()
    }
  })
}

/*
 * Select coders
 */

function coders_select(id, submit) {
  $(id).select2({
    dropdownAutoWidth : true,
    theme: 'bootstrap',
    placeholder: '',
    allowClear: true,
    templateResult: function (data) {
      var $result = $('<span></span>')
      $result.text(data.text)
      return $result
    },
    ajax: {
      url: '/settings/search/',
      dataType: 'json',
      delay: 314,
      data: function (params) {
        return {
          query: 'coders',
          search: params.term,
          page: params.page || 1
        }
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
    },
  }).on('select2:unselecting', function() {
    if (submit) {
      $('button[name="action"][value="' + submit + '"]').prop('disabled', true)
    }
    $(this).data('unselecting', true)
  }).on('select2:opening', function(e) {
    if ($(this).data('unselecting')) {
      $(this).removeData('unselecting')
      e.preventDefault()
    }
  }).on('select2:selecting', function(e) {
    if (submit) {
      $('button[name="action"][value="' + submit + '"]').prop('disabled', false)
    }
  })
  $(id + '-hidden').removeClass('hidden')
}


function escape_html(val) {
  if (typeof val !== 'string') {
    return val
  }
  return val.replace(/&/g, '&amp;')  // First, escape ampersands
            .replace(/"/g, '&quot;') // then double-quotes
            .replace(/'/g, '&#39;')  // and single quotes
            .replace(/</g, '&lt;')   // and less-than signs
            .replace(/>/g, '&gt;');  // and greater-than signs
}

function configure_pagination(paginate_on_scroll = true) {
  $.endlessPaginate({paginateOnScroll: paginate_on_scroll, onCompleted: function () {
    toggle_tooltip()
    inline_button()
    confirm_action()
    checkbox_mouseover_toggle()
    $(window).trigger('resize')
  }})
}


/*
 * checkbox mouseover toggle
 */

var mouse_is_down = false

function checkbox_mouseover_toggle() {
  $('input.mouseover-toggle[type="checkbox"]').removeClass('mouseover-toggle').mouseover(function() {
    if (mouse_is_down) {
      $(this).prop('checked', !$(this).prop('checked'))
    }
  })
}

$(function() {
  $(document).mousedown(function() {
    mouse_is_down = true
  }).mouseup(function() {
    mouse_is_down = false
  })
  checkbox_mouseover_toggle()
})


/*
 * Clear url parameters
 */

function clear_url_parameters() {
  var url = new URL(window.location.href)
  if (url.searchParams.has('search') || url.searchParams.has('sort_order')) {
    var disabled_fields = new Set(['timeline', 'charts', 'fullscreen', 'play', 'full_table', 'unfreezing'])
    var to_remove = new Set()
    var remove_sort = true
    var sort_orders = new Array()
    for ([field, value] of url.searchParams.entries()) {
      if (field == 'sort_order') {
        sort_orders.push(value)
      } else if (field.startsWith('sort')) {
        remove_sort = false
      }
      var disabled = disabled_fields.has(field) || field.startsWith('with_')
      if ((disabled && value == 'off') || (!disabled && !value) || (field == 'groupby' && value == 'none')) {
        to_remove.add(field)
      } else {
        to_remove.delete(field)
      }
    }
    remove_sort = remove_sort || [...to_remove].some((x) => x.startsWith('sort'))
    if (remove_sort) {
      to_remove.add('sort_order')
    }
    if (sort_orders.length > 1) {
      update_urls_params({sort_order: sort_orders[sort_orders.length - 1]})
    }
    if (to_remove) {
      to_remove = [...to_remove].reduce((obj, key) => { obj[key] = undefined; return obj }, {})
      update_urls_params(to_remove)
    }
  }
}

$(clear_url_parameters)


/*
 * user locale
 */

function user_locale() {
  return navigator.language || navigator.userLanguage || navigator.browserLanguage || navigator.systemLanguage || 'en'
}

function is_12_hour_clock() {
  var time_format_options = {hour: 'numeric', minute: 'numeric'}
  var date_time_format = new Intl.DateTimeFormat(user_locale(), time_format_options)
  var time_parts = date_time_format.formatToParts(new Date())
  return time_parts.some(time_part => time_part.type === 'dayPeriod')
}


/*
 * select2
 */

$(() => {
  $('[data-init="select2"]').select2({theme: 'bootstrap', dropdownAutoWidth: true})

  $(document).on('select2:open', (e) => {
    const search_field = document.querySelector('.select2-container--open .select2-search__field')
    if (search_field) {
      search_field.focus()
    }
  })
})

function show_extra(element) {
  var $element = $(element)
  var extra_id = $element.data('id')
  var $extra = $('#' + extra_id)
  $extra.toggleClass('hidden')

  var text = $element.data('toggle-text') || 'hide'
  $element.data('toggle-text', $element.text())
  $element.text(text)
}

function show_field_to_select(event, element, field_id) {
  $(element).closest('.field-to-select').remove()
  $field = $('#' + field_id)
  $field.prop('disabled', false)
  $field.closest('.field-to-select').removeClass('hidden')
  clear_tooltip()
  event.preventDefault()
  $field.select2('open')
  return false
}

function show_field_to_input(event, element, field_id) {
  $(element).closest('.input-group').remove()
  $field = $('#' + field_id)
  $field.prop('disabled', false)
  $field.closest('.field-to-input').removeClass('hidden')
  clear_tooltip()
  event.preventDefault()
  return false
}

/*
 * Starred
 */

function restarred() {
  var total_height = 0
  var selector = '.starred'
  var thead_height = $('#table-inner-scroll thead').height() || 0
  var offset_height = 0
  var total_count = 0
  $(selector).each(function() {
    total_height += $(this).height()
    total_count += 1
  }).each(function(index) {
    var el = $(this)
    var selection = $.browser.firefox? el.find('td') : el
    selection.css({
      'top': offset_height + thead_height - index,
      'bottom': total_height - offset_height - el.height() - (total_count - index + 1),
    })
    offset_height += el.height()
  }).css('z-index', '')
}

/*
 * toastify notifications
 */

Toastify.defaults.style = {}
Toastify.defaults.position = 'right'
Toastify.defaults.gravity= 'bottom'
Toastify.defaults.stopOnFocus = true
Toastify.defaults.duration = 4000
Toastify.defaults.escapeMarkup = true

function notify(message, type = 'success', duration = Toastify.defaults.duration) {
  var escapeHTML = Toastify.defaults.escapeMarkup
  if (typeof type == 'object') {
    var options = type
    type = options.type ?? 'success'
    duration = options.duration ?? duration
    escapeHTML = options.escapeHTML ?? escapeHTML
  }
  type = {error: 'danger', warn: 'warning'}[type] || type
  if (!['danger', 'warning', 'success', 'info'].includes(type)) {
    type = 'undefined'
  }

  var toastify = Toastify({
    text: message,
    duration: duration,
    escapeMarkup: escapeHTML,
    className: `toastify-bootstrap alert alert-${type}`,
  })
  toastify.showToast()
  const toastElement = $(toastify.toastElement)

  const progressBar = $('<div>', {
    class: `progress-bar-${type}`,
    style: `
      position: absolute;
      bottom: 0;
      left: 0;
      width: 100%;
      height: 3px;
      margin: -3px -1px;
      animation: progress-animation ${Math.floor(duration / 1000)}s linear;
    `,
  }).on('animationend', () => { progressBar.css('width', '0%') })
  toastElement.append(progressBar)

  if (Toastify.defaults.stopOnFocus) {
    toastElement.on('mouseenter', () => {
      progressBar.css('animation', 'none')
      progressBar.toggleClass('hidden')
    }).on('mouseleave', () => {
      progressBar.css('animation', `progress-animation ${Math.floor(duration / 1000)}s linear`)
      progressBar.toggleClass('hidden')
    })
  }
  setTimeout(() => toastElement.effect('shake'), 300)
}


/*
 * Modal
 */

function toggle_modal_fullscreen(btn) {
  $(btn).toggleClass('active')
  $(btn).closest('.modal').toggleClass('fullscreen')
  $(btn).find('i').toggleClass('fa-compress-arrows-alt').toggleClass('fa-expand-arrows-alt')
}


/*
 * Expand trimmer text
 */

function expand_trimmed_text(event, element) {
  $(element).prev('.expandable-text').toggleClass('expandable-text')
  $(element).remove()
  $(window).trigger('resize')
  event.preventDefault()
  return false
}

/*
 * Table sticky
 */

function get_effective_background(element) {
  let bg = window.getComputedStyle(element).backgroundColor
  if ((bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') && element.parentElement) {
    return get_effective_background(element.parentElement)
  }
  return bg
}

function update_table_sticky_side(side) {
  var attr_width = 'sticky-' + side + '-width'
  $('table').data(attr_width, 0)

  var columns = $('tr:nth-child(1) th.sticky-' + side + '-column')
  if (side == 'right') {
    columns = $(columns.get().reverse())
  }

  columns.each(function() {
    var table = $(this).closest('table')
    var width = table.data(attr_width) || 0
    var index_column = $(this).index()
    var max_width = 0

    var container = table.closest('.table-responsive')
    var rows = container.find('tr:not(".endless_container")').find('td,th').filter(':nth-child(' + (index_column + 1) + ')')

    rows.each(function() {
      var cell = $(this)
      max_width = Math.max(max_width, cell.outerWidth())
      cell.addClass('sticky-' + side + '-column')
      cell.css(side, width)
      var tr = cell.parent()[0]
      if (!tr.style.backgroundColor) {
        var bg = get_effective_background(tr)
        tr.style.backgroundColor = bg
      }
    })
    table.data(attr_width, width + max_width)
  })
}

function update_table_tr_hover() {
  $('table.table-hover tr:not(.sticky-hovered):has(td)').addClass('sticky-hovered').hover(
    function() {
      var $el = $(this)
      if (this.style.backgroundColor) {
        $el.data('background-color', this.style.backgroundColor)
        this.style.backgroundColor = ''
      }
    },
    function() {
      var $el = $(this)
      if ($el.data('background-color')) {
        this.style.backgroundColor = $el.data('background-color')
        $el.data('background-color', '')
      }
    }
  )
}

function update_table_sticky() {
  $('tr.header-problems').css('top', $('tr.header-row:first').height())

  var width = 0
  var seen = []
  $('tr .sticky-column').each(function() {
    var column = $(this).attr('data-sticky-column')
    if (seen[column]) {
      return
    }
    seen[column] = true
    $('tr .' + column).css('left', width)
    width += $(this).outerWidth()
  })

  update_table_sticky_side('left')
  update_table_sticky_side('right')

  update_table_tr_hover()
}

// Fixed transparent table header
$(function() {
  $('table tr').each(function() {
    $(this).css('background-color', get_effective_background(this))
  })
  update_table_tr_hover()
})


/*
 * Table scroll appearance
 */


function table_scroll_appearance() {
  $('.table-responsive:has(table)').each(function() {
    var container = $(this)
    var table = container.find('table')
    if (container.width() && this.scrollWidth && container.width() + 20 < this.scrollWidth) {
      table.addClass('table-scrolling')
      table.find('th[data-table-scrolling-class]').each(function() {
        var new_class = $(this).attr('data-table-scrolling-class')
        var table = $(this).closest('table')
        var index_column = $(this).index()
        table.find('tr').find('td,th').filter(':nth-child(' + (index_column + 1) + ')').addClass(new_class)
      })
    } else {
      table.removeClass('table-scrolling')
    }
  })
}

$(() => {
  $(window).resize(table_scroll_appearance)
  table_scroll_appearance()
})


/*
 * Add to coder list
 */

function add_to_coder_list(element, event) {
  var $el = $(element)
  var url = $el.data('url')
  var uuid = $el.data('uuid')
  var account = $el.data('account')

  $el.find('i').toggleClass('fa-fade')

  $.ajax({
    type: 'POST',
    url: url,
    data: {
      pk: coder_pk,
      uuid: uuid,
      account: account,
    },
    success: function(data) {
      data['messages'].forEach(function(message) {
        notify(message.message, message.level)
      })
    },
    error: function(response) {
      $el.effect('shake')
      log_ajax_error(response)
    },
    complete: function(data) {
      $el.find('i').toggleClass('fa-fade')
    },
  })

  event.preventDefault()
  return false
}
