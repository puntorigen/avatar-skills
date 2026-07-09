import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("png");
Config.setOverwriteOutput(true);
Config.setEntryPoint("src/index.ts");
Config.setCodec("prores");
Config.setProResProfile("4444");
Config.setPixelFormat("yuva444p10le");
