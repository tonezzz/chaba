#!/usr/bin/env node
import yargs from 'yargs';
import { hideBin } from 'yargs/helpers';
import { loadConfig } from '../config/loader.js';
import { runTask } from '../core/tasks/runner.js';

const cli = yargs(hideBin(process.argv))
  .scriptName('service-installer')
  .usage('$0 <cmd> [args]')
  .option('config', {
    alias: 'c',
    describe: 'Path to deployment config file',
    type: 'string',
    default: 'configs/targets.example.yaml'
  })
  .command(
    'deploy [service]',
    'Deploys specified service to targets',
    (y) =>
      y
        .positional('service', {
          describe: 'Service identifier defined in config',
          type: 'string',
          demandOption: true
        })
        .option('dry-run', {
          describe: 'Simulate actions without executing remote commands',
          type: 'boolean',
          default: false
        }),
    async (argv) => {
      const config = await loadConfig(argv.config);
      await runTask('deploy', {
        service: argv.service,
        dryRun: argv.dryRun,
        config
      });
    }
  )
  .command(
    'status [service]',
    'Check deployment status on all targets',
    (y) =>
      y.positional('service', {
        describe: 'Service identifier defined in config',
        type: 'string',
        demandOption: true
      }),
    async (argv) => {
      const config = await loadConfig(argv.config);
      await runTask('status', {
        service: argv.service,
        config
      });
    }
  )
  .demandCommand(1)
  .strict()
  .help();

cli.parse();
