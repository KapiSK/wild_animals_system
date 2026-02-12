$(function(){
	"use strict";
	var gnavNav = $('.gnav_nav');
	var gnavNavLiA = $('.gnav_nav > li > a');
	var gnavBtnArea = $('.gnav_btn_area');
	var gnavBtn = $('.gnav_btn');

	/* グローバルナビゲーション全体 スマホ時オープンクローズ */
	gnavBtnArea.on('click',function(){
		// リセット
		$('.gnav_nav li').removeClass('is_gnav_nav-current');
		$('.gnav_nav li a').removeClass('is_gnav_sp_mega_open');
		$('.gnav_nav li .gnav_nav-mega').removeClass('is_gnav_nav-mega is_gnav_sp_nav-mega');

		if ( gnavNav.hasClass('is_gnav_nav')){
			gnavNav.removeClass('is_gnav_nav'); // クローズ
		} else {
			gnavNav.addClass('is_gnav_nav'); // オープン
		}
		gnavBtnArea.toggleClass('is_gnav_btn_area');
		gnavBtn.toggleClass('is_gnav_btn');
	});

	/* グローバルナビゲーション スマホ時 各メニュー項目オープンクローズ */
	gnavNavLiA.on('click.spMega', function(){
		if (gnavBtnArea.hasClass('is_gnav_btn_area')){
			if ($(this).hasClass('is_gnav_sp_mega_open')){
				$(this).removeClass('is_gnav_sp_mega_open');
				$(this).next().removeClass('is_gnav_sp_nav-mega');
				$(this).parent().removeClass('is_gnav_nav-current');
			} else {
				$(this).addClass('is_gnav_sp_mega_open');
				$(this).next().addClass('is_gnav_sp_nav-mega');
				$(this).parent().addClass('is_gnav_nav-current');
			}
		}
	});
});
