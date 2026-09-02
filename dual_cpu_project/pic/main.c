/*
 * PIC12F629 Power Controller for Trail Camera
 *
 * コンパイラ: XC8 (Microchip)
 * ターゲット: PIC12F629
 *
 * 概要:
 * PIRセンサーからの割り込み検知のみでスリープから復帰し、
 * MOSFETをONにしてESP32システム全体へ給電する極低消費電力の電源管理プログラム。
 * ESP32からの処理完了信号(または3分タイムアウト)でMOSFETをOFFにして再度スリープへ入る。
 */

// --- コンフィグレーションビットの設定 ---
#pragma config FOSC =                                                          \
    INTRCIO // 内部オシレータ使用 (GP4/GP5はデジタルI/Oとして使用)
#pragma config WDTE =                                                          \
    OFF // ウォッチドッグタイマー無効 (スリープ時の消費電力を下げるため)
#pragma config PWRTE = ON // パワーアップタイマー有効
#pragma config MCLRE =                                                         \
    OFF // GP3/MCLRピンはデジタル入力として使用(内部でVDDにプルアップ)
#pragma config BOREN = OFF // ブラウンアウト・リセット無効
#pragma config CP = OFF    // コードプロテクト無効
#pragma config CPD = OFF   // データプロテクト無効

#include <stdint.h>
#include <xc.h>

// 内部クロック周波数の定義 (__delay_ms()関数で使用)
#define _XTAL_FREQ 4000000 // 4MHz

// --- ピン割り当て ---
#define PIN_MOSFET GP0    // 出力: xiaoの電源制御 (HIGHでMOSFET ON)
#define PIN_XIAO_DONE GP1 // 入力: xiaoからの処理完了信号 (HIGHで完了)
#define PIN_PIR GP2       // 入力: PIRセンサー (状態変化割り込み IOC を使用)
#define PIN_XIAO_SIG GP4  // 出力: xiaoへの信号
#define PIN_LED GP5       // 出力: LED

// --- パラメータ設定 ---
// タイムアウト時間（約100ms * 1800回 = 180秒 = 3分）
#define TIMEOUT_MAX_COUNT 1800

void main(void) {
  // --- 初期化 ---
  // コンパレータの無効化（デジタルI/Oとして使うため必須）
  CMCON = 0x07;

  // GPIOの入出力方向設定 (0=出力, 1=入力)
  // GP0(MOSFET) = 出力(0)
  // GP1(XIAO_DONE) = 入力(1)
  // GP2(PIR) = 入力(1)
  // GP3(MCLR) = 入力(1) - 入力専用
  // GP4(XIAO_SIG), GP5(LED) = 出力(0)
  TRISIO = 0b00001110;

  // GPIOの初期出力値設定 (すべてLOW)
  GPIO = 0x00;

  // --- デバッグ用：起動確認のLED点滅 (3回) ---
  for (uint8_t i = 0; i < 3; i++) {
    PIN_LED = 1;
    __delay_ms(200);
    PIN_LED = 0;
    __delay_ms(200);
  }

  // --- 割り込み設定 ---
  // GP2(PIR)ピンの状態変化割り込み(Interrupt On Change)を有効化
  IOC = 0b00000100;

  // 割り込み設定
  GPIE = 1; // GPIO状態変化割り込み許可

  // 【重要バグ修正】
  // GIE (グローバル割り込み) を 1 にしてしまうと、スリープから復帰した際に
  // 割り込み処理関数（ISR）にジャンプしようとしてプログラムがクラッシュ・リセットしてしまいます。
  // スリープからの復帰（そのまま次の行へ進む）だけを行いたい場合は GIE = 0
  // にする必要があります。
  GIE = 0;

  // --- メインループ ---
  while (1) {
    // 1. xiaoへの給電等をOFF
    PIN_MOSFET = 0;
    PIN_XIAO_SIG = 0;
    PIN_LED = 0;

    // スリープ前の割り込みフラグクリア処理
    // (直前の状態を読んでからフラグを降ろすのが仕様)
    volatile uint8_t dummy = GPIO;
    GPIF = 0;

    // 2. 超低消費電力スリープモードへ移行
    // ※この間、PIRがHIGHに変化するまで電力をほとんど消費しません(1μA以下)
    SLEEP();

    // ------------------------------------------------
    // 3. スリープから復帰（PIR検知）
    // ------------------------------------------------

    // チャタリングやノイズ対策のため少し待つ
    __delay_ms(50);

    // PIRが本当にHIGHか確認
    if (PIN_PIR == 1) {

      // xiaoへの給電をON、信号出力、LED点灯
      PIN_MOSFET = 1;
      PIN_XIAO_SIG = 1;
      PIN_LED = 1;

      // ESP32がブートし、ピン状態が安定するまで待機（起動直後の誤検知防止）
      // デバッグ用：待機中はLEDを細かく点滅させて動作確認
      for (uint8_t i = 0; i < 15; i++) { // 200ms x 15 = 3000ms
        PIN_LED = 1;
        __delay_ms(100);
        PIN_LED = 0;
        __delay_ms(100);
      }

      // 4. xiaoの処理完了またはタイムアウト待ちループ
      uint16_t timeout_counter = 0;
      while (timeout_counter < TIMEOUT_MAX_COUNT) {
        // xiaoから「処理完了」のHIGH信号が来たら抜ける
        if (PIN_XIAO_DONE == 1) {
          break;
        }

        // 100ms 待機してカウンタを進める
        __delay_ms(100);
        timeout_counter++;

        // デバッグ用：ESP32処理待ち中はLEDを点滅 (約500ms周期)
        if (timeout_counter % 5 == 0) {
          PIN_LED ^= 1;
        }
      }

      // 5.
      // 処理完了（またはタイムアウト）。ループを抜けたので出力をOFFにして再度スリープの準備へ
      PIN_MOSFET = 0;
      PIN_XIAO_SIG = 0;
      PIN_LED = 0;

      // PIRセンサーが反応し続けている（動物がまだ前にいる等）場合、
      // すぐにスリープに入ると即座に起きてしまうため、PIRがLOWに落ち着くまで待機する
      while (PIN_PIR == 1) {
        __delay_ms(500);
        // ピンの状態が異常になるのを防ぐため、ここでも確実に出力をOFFに保つ
        PIN_MOSFET = 0;
        PIN_XIAO_SIG = 0;
        PIN_LED = 0;
      }

      // 連続撮影を防ぐため、5分間のインターバル（不感時間）を設ける
      // (100ms * 3000回 = 300秒 = 5分)
      for (uint16_t i = 0; i < 3000; i++) {
        __delay_ms(100);
        // デバッグ用：不感時間中はLEDをゆっくり点滅 (1秒ごとに反転)
        if (i % 10 == 0) {
          PIN_LED ^= 1;
        }
      }
      PIN_LED = 0; // 最後に確実に消灯

      // 状態が落ち着いたのでフラグをクリア
      dummy = GPIO;
      GPIF = 0;
    }
  }
}
